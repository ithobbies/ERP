import calendar
from decimal import Decimal
from django.db.models import Sum, F, DecimalField, ExpressionWrapper
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework import generics, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response

from .models import Equipment, ShiftReport, EquipmentTimeLog, User, TmcCatalog, TmcWriteOff, MaintenanceRecord
from .serializers import (
    EquipmentSerializer,
    ShiftReportSerializer,
    LoginSerializer,
    TmcCatalogSerializer,
    TmcWriteOffSerializer,
    MaintenanceRecordSerializer,
)


class LoginAPIView(generics.GenericAPIView):
    serializer_class = LoginSerializer
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.validated_data)


class EquipmentListAPIView(generics.ListAPIView):
    queryset = Equipment.objects.filter(is_active=True).order_by('name')
    serializer_class = EquipmentSerializer


class ShiftReportViewSet(viewsets.ModelViewSet):
    queryset = ShiftReport.objects.select_related('author', 'production_metrics').prefetch_related('reservoir_levels', 'equipment_time_logs')
    serializer_class = ShiftReportSerializer

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role in [User.Roles.CHIEF, User.Roles.DEPUTY_ENGINEERING, User.Roles.DEPUTY_PRODUCTION]:
            return self.queryset
        return self.queryset.filter(author=user)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        report = self.get_object()
        user = request.user
        allowed = user.is_superuser or user.role == User.Roles.CHIEF or user.can_approve_reports
        if not allowed:
            return Response({'detail': 'Недостатньо прав для затвердження.'}, status=status.HTTP_403_FORBIDDEN)
        report.is_locked = True
        report.save(update_fields=['is_locked'])
        return Response({'detail': 'Рапорт затверджено.', 'id': report.id, 'is_locked': report.is_locked})


class TmcCatalogListAPIView(generics.ListAPIView):
    serializer_class = TmcCatalogSerializer

    def get_queryset(self):
        q = self.request.query_params.get('q')
        qs = TmcCatalog.objects.all().order_by('name')
        if q:
            qs = qs.filter(name__icontains=q) | qs.filter(nomenclature_id__icontains=q)
        return qs


class TmcWriteOffCreateAPIView(generics.CreateAPIView):
    serializer_class = TmcWriteOffSerializer


class MaintenanceRecordViewSet(viewsets.ModelViewSet):
    serializer_class = MaintenanceRecordSerializer
    queryset = MaintenanceRecord.objects.select_related('equipment', 'author').all().order_by('-work_date')

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_summary(request):
    now = timezone.localdate()
    month_start = now.replace(day=1)
    month_days = calendar.monthrange(now.year, now.month)[1]

    reports = ShiftReport.objects.filter(shift_date__gte=month_start, shift_date__lte=now).select_related('production_metrics')

    total_water = reports.aggregate(total=Coalesce(Sum('production_metrics__vol_water'), 0))['total']
    total_slurry = reports.aggregate(total=Coalesce(Sum('production_metrics__vol_slurry'), 0))['total']

    logs = EquipmentTimeLog.objects.filter(shift_report__in=reports)
    total_work = logs.aggregate(total=Coalesce(Sum('work_hours'), 0))['total']
    total_reserve = logs.aggregate(total=Coalesce(Sum('reserve_hours'), 0))['total']
    total_count = logs.count()
    avg_ktg = Decimal('0')
    if total_count:
        avg_ktg = ((Decimal(total_work) + Decimal(total_reserve)) / (Decimal('12') * Decimal(total_count))) * Decimal('100')

    total_energy = reports.aggregate(total=Coalesce(Sum('production_metrics__energy_abs'), 0))['total']
    avg_specific_energy = Decimal('0')
    if total_water and Decimal(total_water) > 0:
        avg_specific_energy = Decimal(total_energy) / Decimal(total_water)

    by_day = reports.values('shift_date').order_by('shift_date').annotate(
        water=Coalesce(Sum('production_metrics__vol_water'), 0),
        slurry=Coalesce(Sum('production_metrics__vol_slurry'), 0),
    )

    downtime = logs.aggregate(
        mech=Coalesce(Sum('downtime_mech'), 0),
        el=Coalesce(Sum('downtime_el'), 0),
        tech=Coalesce(Sum('downtime_tech'), 0),
    )

    month_writeoffs = TmcWriteOff.objects.filter(writeoff_date__gte=month_start, writeoff_date__lte=now)
    tmc_start_balance = TmcCatalog.objects.aggregate(
        total=Coalesce(Sum(ExpressionWrapper(F('current_stock') * F('price_per_unit'), output_field=DecimalField())), 0)
    )['total']
    written_off_amount = month_writeoffs.aggregate(total=Coalesce(Sum('amount'), 0))['total']
    avg_stock = Decimal(tmc_start_balance) + (Decimal(written_off_amount) / Decimal('2') if written_off_amount else Decimal('0'))
    turnover_days = Decimal('0')
    if written_off_amount and Decimal(written_off_amount) > 0:
        turnover_days = (avg_stock * Decimal(month_days)) / Decimal(written_off_amount)

    top_writeoffs = (
        month_writeoffs.values('item__name')
        .annotate(amount=Coalesce(Sum('amount'), 0))
        .order_by('-amount')[:3]
    )

    response_data = {
        'kpis': {
            'total_water_mtd': round(Decimal(total_water), 2),
            'total_slurry_mtd': round(Decimal(total_slurry), 2),
            'avg_ktg_percent': round(avg_ktg, 2),
            'avg_specific_energy': round(avg_specific_energy, 4),
        },
        'volume_chart': {
            'labels': [entry['shift_date'].day for entry in by_day],
            'water': [float(entry['water']) for entry in by_day],
            'slurry': [float(entry['slurry']) for entry in by_day],
        },
        'downtime': {
            'mechanical': round(Decimal(downtime['mech']), 2),
            'electrical': round(Decimal(downtime['el']), 2),
            'technological': round(Decimal(downtime['tech']), 2),
        },
        'tmc': {
            'current_balance': round(Decimal(tmc_start_balance), 2),
            'written_off': round(Decimal(written_off_amount), 2),
            'turnover_days': round(turnover_days, 2),
            'top_writeoffs': list(top_writeoffs),
        },
    }
    return Response(response_data)
