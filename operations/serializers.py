from datetime import timedelta
from decimal import Decimal
from django.contrib.auth import authenticate
from django.db import transaction
from django.db.models import Sum, F
from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from .models import (
    User,
    Equipment,
    LevelVolumeTable,
    TmcCatalog,
    ShiftReport,
    ProductionMetrics,
    ReservoirLevel,
    EquipmentTimeLog,
    MaintenanceRecord,
    TmcWriteOff,
)


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = authenticate(username=attrs['username'], password=attrs['password'])
        if not user:
            raise serializers.ValidationError('Невірний логін або пароль.')
        refresh = RefreshToken.for_user(user)
        return {
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'role': user.role,
            'username': user.username,
        }


class EquipmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Equipment
        fields = '__all__'


class ProductionMetricsSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductionMetrics
        exclude = ('shift_report',)


class ReservoirLevelSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReservoirLevel
        exclude = ('shift_report', 'calc_volume_start', 'calc_volume_end')


class EquipmentTimeLogSerializer(serializers.ModelSerializer):
    equipment_name = serializers.CharField(source='equipment.name', read_only=True)

    class Meta:
        model = EquipmentTimeLog
        exclude = ('shift_report',)

    def validate(self, attrs):
        total = sum(
            Decimal(str(attrs.get(field, 0)))
            for field in ['work_hours', 'reserve_hours', 'downtime_mech', 'downtime_el', 'downtime_tech']
        )
        if total != Decimal('12'):
            raise serializers.ValidationError('Сума годин по рядку має дорівнювати 12.')
        return attrs


class ShiftReportSerializer(serializers.ModelSerializer):
    production_metrics = ProductionMetricsSerializer()
    reservoir_levels = ReservoirLevelSerializer(many=True)
    equipment_time_logs = EquipmentTimeLogSerializer(many=True)

    class Meta:
        model = ShiftReport
        fields = (
            'id',
            'author',
            'shift_date',
            'shift_number',
            'is_locked',
            'created_at',
            'updated_at',
            'production_metrics',
            'reservoir_levels',
            'equipment_time_logs',
        )
        read_only_fields = ('author', 'is_locked', 'created_at', 'updated_at')

    def _enforce_time_lock(self, instance):
        request = self.context['request']
        if request.user.is_superuser:
            return
        if request.user.role not in [User.Roles.OPERATOR, User.Roles.ENGINEER]:
            return
        if request.user != instance.author:
            raise serializers.ValidationError('Редагувати може лише автор запису.')
        if instance.is_locked:
            raise serializers.ValidationError('Рапорт затверджено і заблоковано для редагування.')
        if timezone.now() - instance.created_at > timedelta(hours=12):
            raise serializers.ValidationError('Ліміт редагування 12 годин вичерпано.')

    def validate_shift_number(self, value):
        if value not in [1, 2, 3, 4]:
            raise serializers.ValidationError('Номер зміни має бути в межах 1..4.')
        return value

    def _interpolate_volume(self, reservoir_name, level_m):
        level_cm = int(Decimal(level_m) * 100)
        lower = (
            LevelVolumeTable.objects.filter(reservoir_name=reservoir_name, level_cm__lte=level_cm)
            .order_by('-level_cm')
            .first()
        )
        upper = (
            LevelVolumeTable.objects.filter(reservoir_name=reservoir_name, level_cm__gte=level_cm)
            .order_by('level_cm')
            .first()
        )

        if not lower or not upper:
            raise serializers.ValidationError(
                f'Для {reservoir_name} бракує даних у таблиці калібрування для рівня {level_cm} см.'
            )

        if lower.level_cm == upper.level_cm:
            return lower.volume_m3

        l1, l2 = Decimal(lower.level_cm), Decimal(upper.level_cm)
        v1, v2 = lower.volume_m3, upper.volume_m3
        result = v1 + ((v2 - v1) / (l2 - l1)) * (Decimal(level_cm) - l1)
        return result.quantize(Decimal('0.01'))

    @transaction.atomic
    def create(self, validated_data):
        pm_data = validated_data.pop('production_metrics')
        rl_data = validated_data.pop('reservoir_levels')
        etl_data = validated_data.pop('equipment_time_logs')

        report = ShiftReport.objects.create(author=self.context['request'].user, **validated_data)
        ProductionMetrics.objects.create(shift_report=report, **pm_data)

        for reservoir in rl_data:
            calc_start = self._interpolate_volume(reservoir['reservoir_name'], reservoir['level_start_m'])
            calc_end = self._interpolate_volume(reservoir['reservoir_name'], reservoir['level_end_m'])
            ReservoirLevel.objects.create(
                shift_report=report,
                calc_volume_start=calc_start,
                calc_volume_end=calc_end,
                **reservoir,
            )

        for log in etl_data:
            EquipmentTimeLog.objects.create(shift_report=report, **log)

        return report

    @transaction.atomic
    def update(self, instance, validated_data):
        self._enforce_time_lock(instance)

        pm_data = validated_data.pop('production_metrics', None)
        rl_data = validated_data.pop('reservoir_levels', None)
        etl_data = validated_data.pop('equipment_time_logs', None)

        instance.shift_date = validated_data.get('shift_date', instance.shift_date)
        instance.shift_number = validated_data.get('shift_number', instance.shift_number)
        instance.save()

        if pm_data:
            for key, value in pm_data.items():
                setattr(instance.production_metrics, key, value)
            instance.production_metrics.save()

        if rl_data is not None:
            instance.reservoir_levels.all().delete()
            for reservoir in rl_data:
                calc_start = self._interpolate_volume(reservoir['reservoir_name'], reservoir['level_start_m'])
                calc_end = self._interpolate_volume(reservoir['reservoir_name'], reservoir['level_end_m'])
                ReservoirLevel.objects.create(
                    shift_report=instance,
                    calc_volume_start=calc_start,
                    calc_volume_end=calc_end,
                    **reservoir,
                )

        if etl_data is not None:
            instance.equipment_time_logs.all().delete()
            for log in etl_data:
                EquipmentTimeLog.objects.create(shift_report=instance, **log)

        return instance


class MaintenanceRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = MaintenanceRecord
        fields = '__all__'
        read_only_fields = ('author',)


class TmcCatalogSerializer(serializers.ModelSerializer):
    class Meta:
        model = TmcCatalog
        fields = '__all__'


class TmcWriteOffSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source='item.name', read_only=True)

    class Meta:
        model = TmcWriteOff
        fields = '__all__'
        read_only_fields = ('author', 'amount')

    @transaction.atomic
    def create(self, validated_data):
        item = TmcCatalog.objects.select_for_update().get(pk=validated_data['item'].pk)
        quantity = validated_data['quantity']
        if quantity <= 0:
            raise serializers.ValidationError('Кількість списання має бути більшою за нуль.')
        if quantity > item.current_stock:
            raise serializers.ValidationError('Недостатній залишок ТМЦ на складі.')
        item.current_stock -= quantity
        item.save(update_fields=['current_stock'])
        validated_data['item'] = item
        return TmcWriteOff.objects.create(author=self.context['request'].user, **validated_data)
