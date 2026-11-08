from django.urls import path

from . import views

urlpatterns = [
    path('services/', views.receipt_list, name='receipt_list'),
    path('services/add/', views.receipt_add, name='receipt_add'),
    path('properties/<int:property_pk>/receipts/new/', views.receipt_create, name='receipt_create'),
    path('properties/<int:property_pk>/month/', views.month_save, name='month_save'),
    path('receipts/<int:pk>/edit/', views.receipt_edit, name='receipt_edit'),
    path('receipts/<int:pk>/delete/', views.receipt_delete, name='receipt_delete'),
]
