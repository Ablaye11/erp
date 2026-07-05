from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import FileResponse, Http404
from accounts.views import login_view, logout_view
import os

from rest_framework.routers import DefaultRouter
from rest_framework.authtoken.views import obtain_auth_token
from core.api_views import StudentProfileViewSet, GradeViewSet, AttendanceViewSet

router = DefaultRouter()
router.register('students', StudentProfileViewSet, basename='api-students')
router.register('grades', GradeViewSet, basename='api-grades')
router.register('attendance', AttendanceViewSet, basename='api-attendance')


def serve_sw(request):
    """Serve the Service Worker from the root path so it can control the full scope."""
    sw_path = os.path.join(settings.BASE_DIR, 'static', 'sw.js')
    if os.path.exists(sw_path):
        response = FileResponse(open(sw_path, 'rb'), content_type='application/javascript')
        response['Service-Worker-Allowed'] = '/'
        response['Cache-Control'] = 'no-cache'
        return response
    raise Http404("sw.js not found")


urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    path('sw.js', serve_sw, name='service_worker'),
    path('api/v1/', include(router.urls)),
    path('api/v1/auth-token/', obtain_auth_token, name='api_token'),
    path('', include('core.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
