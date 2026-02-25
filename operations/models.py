from decimal import Decimal
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    class Roles(models.TextChoices):
        OPERATOR = 'operator', 'Оператор'
        ENGINEER = 'engineer', 'Інженер'
        CHIEF = 'chief', 'Керівник цеху'
        DEPUTY_PRODUCTION = 'deputy_production', 'Заступник з виробництва та планування'
        DEPUTY_ENGINEERING = 'deputy_engineering', 'Заступник з інжинірингу'

    role = models.CharField(max_length=32, choices=Roles.choices, default=Roles.OPERATOR)
    can_approve_reports = models.BooleanField(default=False)


class Equipment(models.Model):
    class Types(models.TextChoices):
        PUMP = 'pump', 'Насос'
        DREDGER = 'dredger', 'Землесос'

    name = models.CharField(max_length=255)
    station = models.CharField(max_length=255)
    type = models.CharField(max_length=16, choices=Types.choices)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class LevelVolumeTable(models.Model):
    class ReservoirNames(models.TextChoices):
        TAILING_1 = 'tailing_1', 'Хвостосховище 1'
        TAILING_2 = 'tailing_2', 'Хвостосховище 2'
        BUFFER_POND = 'buffer_pond', 'Буферний ставок'
        WATER_POND = 'water_pond', 'Ставок об. вод.'
        EMERGENCY_TANK = 'emergency_tank', 'Аварійна ємність'

    reservoir_name = models.CharField(max_length=32, choices=ReservoirNames.choices)
    level_cm = models.IntegerField()
    volume_m3 = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        unique_together = ('reservoir_name', 'level_cm')
        ordering = ('reservoir_name', 'level_cm')


class TmcCatalog(models.Model):
    nomenclature_id = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    current_stock = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    price_per_unit = models.DecimalField(max_digits=14, decimal_places=2)

    def __str__(self):
        return f'{self.nomenclature_id} - {self.name}'


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class ShiftReport(TimeStampedModel):
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name='shift_reports')
    shift_date = models.DateField()
    shift_number = models.PositiveSmallIntegerField()
    is_locked = models.BooleanField(default=False)

    class Meta:
        unique_together = ('shift_date', 'shift_number', 'author')
        ordering = ('-shift_date', '-shift_number')

    def clean(self):
        if self.shift_number not in [1, 2, 3, 4]:
            raise ValidationError('Номер зміни має бути в діапазоні 1-4.')


class ProductionMetrics(models.Model):
    shift_report = models.OneToOneField(ShiftReport, on_delete=models.CASCADE, related_name='production_metrics')
    vol_water = models.DecimalField(max_digits=14, decimal_places=2)
    vol_slurry = models.DecimalField(max_digits=14, decimal_places=2)
    vol_dredge = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    vol_dns3 = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    vol_emergency_drop = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    energy_abs = models.DecimalField(max_digits=14, decimal_places=2)


class ReservoirLevel(models.Model):
    shift_report = models.ForeignKey(ShiftReport, on_delete=models.CASCADE, related_name='reservoir_levels')
    reservoir_name = models.CharField(max_length=32, choices=LevelVolumeTable.ReservoirNames.choices)
    level_start_m = models.DecimalField(max_digits=8, decimal_places=2)
    level_end_m = models.DecimalField(max_digits=8, decimal_places=2)
    calc_volume_start = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    calc_volume_end = models.DecimalField(max_digits=14, decimal_places=2, default=0)


class EquipmentTimeLog(models.Model):
    shift_report = models.ForeignKey(ShiftReport, on_delete=models.CASCADE, related_name='equipment_time_logs')
    equipment = models.ForeignKey(Equipment, on_delete=models.PROTECT, related_name='time_logs')
    work_hours = models.DecimalField(max_digits=5, decimal_places=2)
    reserve_hours = models.DecimalField(max_digits=5, decimal_places=2)
    downtime_mech = models.DecimalField(max_digits=5, decimal_places=2)
    downtime_el = models.DecimalField(max_digits=5, decimal_places=2)
    downtime_tech = models.DecimalField(max_digits=5, decimal_places=2)

    def clean(self):
        total = (self.work_hours + self.reserve_hours + self.downtime_mech + self.downtime_el + self.downtime_tech)
        if total != Decimal('12'):
            raise ValidationError('Сума годин має дорівнювати 12 для однієї зміни.')


class MaintenanceRecord(TimeStampedModel):
    class WorkType(models.TextChoices):
        TO = 'TO', 'ТО'
        PR = 'PR', 'ПР'
        KR = 'KR', 'КР'

    class ContractorCategory(models.TextChoices):
        OWN = 'own', 'Власні сили'
        INTERNAL = 'internal', 'Внутрішні підрядники'
        THIRD_PARTY = 'third_party', 'Треті особи'

    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name='maintenance_records')
    equipment = models.ForeignKey(Equipment, on_delete=models.PROTECT, related_name='maintenance_records')
    work_type = models.CharField(max_length=2, choices=WorkType.choices)
    description = models.TextField()
    contractor_category = models.CharField(max_length=16, choices=ContractorCategory.choices)
    external_services_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    work_date = models.DateField(default=timezone.localdate)


class TmcWriteOff(TimeStampedModel):
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name='tmc_writeoffs')
    maintenance_record = models.ForeignKey(MaintenanceRecord, on_delete=models.SET_NULL, null=True, blank=True, related_name='tmc_writeoffs')
    item = models.ForeignKey(TmcCatalog, on_delete=models.PROTECT, related_name='writeoffs')
    quantity = models.DecimalField(max_digits=14, decimal_places=2)
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    writeoff_date = models.DateField(default=timezone.localdate)

    def save(self, *args, **kwargs):
        self.amount = self.quantity * self.item.price_per_unit
        super().save(*args, **kwargs)
