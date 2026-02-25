from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    LoginAPIView,
    EquipmentListAPIView,
    ShiftReportViewSet,
    dashboard_summary,
    TmcCatalogListAPIView,
    TmcWriteOffCreateAPIView,
    MaintenanceRecordViewSet,
)

router = DefaultRouter()
router.register(r'shift-reports', ShiftReportViewSet, basename='shift-report')
router.register(r'maintenance-records', MaintenanceRecordViewSet, basename='maintenance-record')

urlpatterns = [
    path('auth/login/', LoginAPIView.as_view(), name='login'),
    path('equipment/', EquipmentListAPIView.as_view(), name='equipment-list'),
    path('dashboard/summary/', dashboard_summary, name='dashboard-summary'),
    path('tmc/', TmcCatalogListAPIView.as_view(), name='tmc-list'),
    path('tmc/writeoff/', TmcWriteOffCreateAPIView.as_view(), name='tmc-writeoff'),
    path('', include(router.urls)),
]
