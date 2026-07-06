from core.models import SchoolSettings

def school_settings(request):
    try:
        cfg = SchoolSettings.get()
        return {
            'school_name': cfg.school_name,
            'school_city': cfg.school_city,
            'school_email': cfg.school_email,
            'school_director': cfg.school_director,
            'school_year': cfg.school_year,
        }
    except Exception:
        return {
            'school_name': "École Al-Nour",
            'school_city': "Dakar",
            'school_email': "contact@alnour.sn",
            'school_director': "Babacar Diop",
            'school_year': "2024/2025",
        }
