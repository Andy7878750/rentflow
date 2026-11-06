from django.urls import path

from . import views

urlpatterns = [
    path('', views.property_list, name='property_list'),
    path('new/', views.property_create, name='property_create'),
    path('kinds/', views.kind_add, name='property_kind_add'),
    path('kinds/<int:pk>/delete/', views.kind_delete, name='property_kind_delete'),
    path('<int:pk>/', views.property_detail, name='property_detail'),
    path('<int:pk>/edit/', views.property_edit, name='property_edit'),
    path('<int:pk>/delete/', views.property_delete, name='property_delete'),
]
