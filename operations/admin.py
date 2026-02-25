from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

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


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Ролі', {'fields': ('role', 'can_approve_reports')}),
    )


admin.site.register(Equipment)
admin.site.register(LevelVolumeTable)
admin.site.register(TmcCatalog)
admin.site.register(ShiftReport)
admin.site.register(ProductionMetrics)
admin.site.register(ReservoirLevel)
admin.site.register(EquipmentTimeLog)
admin.site.register(MaintenanceRecord)
admin.site.register(TmcWriteOff)
