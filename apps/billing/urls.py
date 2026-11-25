from django.urls import path

from . import views

urlpatterns = [
    path('services/', views.receipt_list, name='receipt_list'),
    path('services/add/', views.receipt_add, name='receipt_add'),
    path('meters/', views.meter_list, name='meter_list'),
    path('tariffs/', views.tariff_list, name='tariff_list'),
    path('tariffs/<int:pk>/history/', views.tariff_history, name='tariff_history'),
    path('payments/', views.payment_list, name='payment_list'),
    path('payments/<int:pk>/<str:month>/', views.payment_edit, name='payment_edit'),
    path('payments/receipt/<int:pk>/<str:month>/', views.payment_bundle_edit, name='payment_bundle_edit'),
    path('payments/receipt/<int:pk>/', views.payment_bundle, name='payment_bundle'),
    path('payments/merge/<str:month>/', views.payment_merge, name='payment_merge'),
    path('meters/add/', views.meter_add, name='meter_add'),
    path('meters/<int:pk>/remove/', views.meter_remove, name='meter_remove'),
    path('meters/<int:pk>/history/', views.meter_history, name='meter_history'),
    path('properties/<int:property_pk>/services/', views.service_window, name='service_window'),
    path('properties/<int:property_pk>/services/save/', views.service_save, name='service_save'),
    path('properties/<int:property_pk>/meters/save/', views.meter_save, name='meter_save'),
    path('meters/<int:pk>/delete/', views.meter_delete, name='meter_delete'),
    path('properties/<int:property_pk>/month/', views.month_save, name='month_save'),
    path('receipts/<int:pk>/delete/', views.receipt_delete, name='receipt_delete'),
    path('properties/<int:property_pk>/receipts/order/', views.receipt_order, name='receipt_order'),
    path('properties/<int:property_pk>/bill/<int:payer>/', views.bill_print, name='bill_print'),
    path('receipts/<int:pk>/night-weight/', views.receipt_night_weight, name='receipt_night_weight'),
]
