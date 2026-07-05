from core.models import AuditLog

def get_client_ip(request):
    if not request:
        return None
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

def log_audit(request, action, obj=None, changes=None):
    user = None
    ip = None
    if request:
        user = request.user if request.user and request.user.is_authenticated else None
        ip = get_client_ip(request)
    
    model_name = None
    object_id = None
    if obj:
        model_name = obj.__class__.__name__
        object_id = str(obj.pk)
        
    return AuditLog.objects.create(
        user=user,
        action=action,
        model_name=model_name,
        object_id=object_id,
        changes=changes,
        ip_address=ip
    )


def send_system_email(subject, message, recipient_list):
    """Wrapper pour envoyer des emails avec fallback logging."""
    from django.core.mail import send_mail
    from django.conf import settings
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipient_list,
            fail_silently=False,
        )
        return True
    except Exception as e:
        logger.error(f"Erreur d'envoi d'email SMTP : {str(e)}")
        return False

