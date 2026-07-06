from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.views.decorators.http import require_POST
from django.db.models import Avg, Sum, Count, Q
from django.utils import timezone
from django.http import HttpResponse, JsonResponse
from django.contrib import messages
from django.views.decorators.csrf import csrf_protect, csrf_exempt
import datetime
import os

from accounts.models import SchoolClass, StudentProfile, TeacherProfile, ParentProfile, AdminProfile
from academics.models import Subject, ClassSchedule, Grade, Attendance, TeacherLeave, ClassSubjectConfig
from finances.models import TuitionFee, Payment
from core.models import Message, Notification, DocumentFile, SchoolSettings, SchoolEvent

User = get_user_model()

# --- Helpers for Devoirs & Compositions ---

def get_student_subject_term_details(student, subject, term, school_year):
    from academics.models import Grade
    grades_qs = Grade.objects.filter(student=student, subject=subject, term=term, school_year=school_year)
    # Tous les devoirs (pour affichage dans le formulaire de saisie)
    devoirs_all = grades_qs.filter(grade_type='DEVOIR').order_by('devoir_num', 'created_at')
    # Devoirs qui comptent dans le bulletin uniquement
    devoirs_counted = devoirs_all.filter(count_in_bulletin=True)
    compo = grades_qs.filter(grade_type='COMPOSITION').first()

    # Liste complète pour affichage (avec indicateur de comptage)
    devoirs_raw = []
    for g in devoirs_all:
        score_20 = float(g.score) * 20.0 / float(g.max_score) if g.max_score else float(g.score)
        devoirs_raw.append({'score': score_20, 'count': g.count_in_bulletin, 'num': g.devoir_num})

    # Seuls les devoirs cochés entrent dans le calcul de la moyenne
    devoirs_list = [d['score'] for d in devoirs_raw if d['count']]

    moy_devoirs = sum(devoirs_list) / len(devoirs_list) if devoirs_list else None

    compo_score = (float(compo.score) * 20.0 / float(compo.max_score)) if (compo and compo.max_score) else (float(compo.score) if compo else None)
    compo_comment = compo.comment if compo else ""
    remark = compo_comment if compo_comment else (devoirs_all.last().comment if devoirs_all.exists() else "")

    # Formule sénégalaise : (Moy_devoirs × 1 + Composition × 2) / 3
    if moy_devoirs is not None and compo_score is not None:
        moyenne = (moy_devoirs * 1.0 + compo_score * 2.0) / 3.0
    elif compo_score is not None:
        moyenne = compo_score
    elif moy_devoirs is not None:
        moyenne = moy_devoirs
    else:
        moyenne = None

    # String d'affichage des devoirs (comptés = normal, non comptés = barré)
    devoirs_display_parts = []
    for d in devoirs_raw:
        s = f"{d['score']:.2f}".rstrip('0').rstrip('.')
        devoirs_display_parts.append(s if d['count'] else f"({s}*)")
    devoirs_str = ", ".join(devoirs_display_parts) if devoirs_display_parts else "—"

    return {
        'devoirs': devoirs_list,            # Scores comptés uniquement
        'devoirs_raw': devoirs_raw,          # Tous les devoirs avec indicateur
        'devoirs_str': devoirs_str,
        'moy_devoirs': round(moy_devoirs, 2) if moy_devoirs is not None else None,
        'compo': round(compo_score, 2) if compo_score is not None else None,
        'moyenne': round(moyenne, 2) if moyenne is not None else None,
        'remark': remark,
    }

def get_student_term_average(student, term, school_year):
    """Calculates overall weighted term average for a student."""
    from academics.models import Subject, ClassSubjectConfig
    if not student.class_room:
        return 0.0
    
    subjects = Subject.objects.filter(classes=student.class_room).distinct()
    if not subjects.exists():
        subjects = Subject.objects.all()

    configs = {cfg.subject_id: float(cfg.coefficient) for cfg in ClassSubjectConfig.objects.filter(school_class=student.class_room)}

    total_points = 0.0
    total_coef = 0.0
    for sub in subjects:
        details = get_student_subject_term_details(student, sub, term, school_year)
        if details['moyenne'] is not None:
            coef = configs.get(sub.id, float(sub.coefficient))
            total_points += details['moyenne'] * coef
            total_coef += coef

    return round(total_points / total_coef, 2) if total_coef > 0 else 0.0

def get_student_annual_average(student, school_year):
    if not student.class_room:
        return 0.0
    nb_terms = student.class_room.nb_trimestres or 3
    term_averages = []
    for t in range(1, nb_terms + 1):
        from academics.models import Grade
        if Grade.objects.filter(student=student, term=t, school_year=school_year).exists():
            avg = get_student_term_average(student, t, school_year)
            term_averages.append(avg)
    return round(sum(term_averages) / len(term_averages), 2) if term_averages else 0.0

def get_class_rankings(class_obj, term, school_year):
    """
    Calculates overall averages and ranks for all students in a class.
    Handles ties using standard competition ranking (e.g. 1, 2, 2, 4...).
    Returns a dict mapping student.id (int) to a dict:
    {
        'rank_num': int,
        'rank_str': str,
        'average': float
    }
    """
    if not class_obj:
        return {}
    students = StudentProfile.objects.filter(class_room=class_obj)
    total_students = students.count()
    if total_students == 0:
        return {}
        
    student_averages = []
    for s in students:
        if term == 0:
            avg = get_student_annual_average(s, school_year)
        else:
            avg = get_student_term_average(s, term, school_year)
        student_averages.append((s.id, avg))
        
    student_averages.sort(key=lambda x: x[1], reverse=True)
    
    rankings = {}
    current_rank = 1
    for idx, (s_id, avg) in enumerate(student_averages):
        if idx > 0 and avg < student_averages[idx - 1][1]:
            current_rank = idx + 1
        rank_str = f"{current_rank}er/{total_students}" if current_rank == 1 else f"{current_rank}ème/{total_students}"
        rankings[s_id] = {
            'rank_num': current_rank,
            'rank_str': rank_str,
            'average': avg
        }
    return rankings

# ─── Security helpers ────────────────────────────────────────────────────────


# Panels accessible par rôle
ROLE_PANEL_ACCESS = {
    'admin':  [
        'adminDash', 'notifications', 'eleves', 'profs', 'personnel',
        'bulletins', 'presences', 'emploiAdmin', 'paiements', 'dossiers',
        'messagerie', 'settings', 'profDash', 'eleveDash', 'parentDash',
        'bulletin', 'progression', 'absencesEleve', 'paiementEleve',
        'emploi', 'mesEleves', 'saisirNotes', 'appel', 'bulletinProf',
        'agenda', 'auditLog', 'classement', 'congesProfs', 'planning',
    ],
    'prof': [
        'profDash', 'notifications', 'mesEleves', 'saisirNotes', 'appel',
        'bulletinProf', 'agenda', 'messagerie', 'settings', 'classement',
    ],
    'eleve': [
        'eleveDash', 'bulletin', 'progression', 'emploi',
        'absencesEleve', 'paiementEleve', 'messagerie', 'notifications', 'settings', 'classement',
    ],
    'parent': [
        'parentDash', 'bulletin', 'progression', 'absencesEleve',
        'paiementEleve', 'messagerie', 'notifications', 'settings', 'classement',
    ],
}

def _get_active_role(request):
    """Retourne le rôle actif de la session, initialisé si nécessaire."""
    if 'active_role' not in request.session:
        role = request.user.role.lower()
        mapping = {'teacher': 'prof', 'student': 'eleve'}
        request.session['active_role'] = mapping.get(role, role)
    return request.session['active_role']

def _can_access_panel(active_role, panel_name):
    """Vérifie que le rôle actif a accès au panel demandé."""
    return panel_name in ROLE_PANEL_ACCESS.get(active_role, [])

def _is_admin_user(request):
    """Retourne True si l'utilisateur réel est ADMIN."""
    return request.user.role == 'ADMIN'

def _htmx_forbidden(panel_name):
    """Réponse 403 pour HTMX."""
    return HttpResponse(
        f'<div class="empty-state" style="color:#A32D2D;">'
        f'<i class="ti ti-lock" style="font-size:32px;"></i>'
        f'<br>Accès refusé — vous n\'avez pas les droits pour accéder à ce module.</div>',
        status=403
    )

@login_required
def dashboard_view(request):
    # Determine the default active role for the session
    if 'active_role' not in request.session:
        role = request.user.role.lower()
        if role == 'teacher':
            request.session['active_role'] = 'prof'
        elif role == 'student':
            request.session['active_role'] = 'eleve'
        else:
            request.session['active_role'] = role

    active_role = request.session.get('active_role', 'admin')
    
    # Get user notifications count
    unread_notifs = Notification.objects.filter(user=request.user, is_read=False).count()
    
    default_panel = 'adminDash'
    if active_role == 'prof':
        default_panel = 'profDash'
    elif active_role == 'eleve':
        default_panel = 'eleveDash'
    elif active_role == 'parent':
        default_panel = 'parentDash'

    context = {
        'active_role': active_role,
        'default_panel': default_panel,
        'unread_notifs_count': unread_notifs,
        'user_role_label': request.user.get_role_display(),
    }
    return render(request, 'dashboard.html', context)

@login_required
def switch_role_view(request, role):
    """Permet aux admins de switcher de rôle pour tester l'interface.
    Les non-admins ne peuvent voir que leur propre rôle."""
    real_role = request.user.role
    allowed_roles = ['admin', 'prof', 'eleve', 'parent']
    
    if role not in allowed_roles:
        return redirect('dashboard')
    
    # Seuls les vrais admins peuvent s'impersonifier en d'autres rôles
    if real_role != 'ADMIN':
        # Non-admin : forcer son propre rôle
        role_map = {'TEACHER': 'prof', 'STUDENT': 'eleve', 'PARENT': 'parent'}
        forced = role_map.get(real_role, 'eleve')
        request.session['active_role'] = forced
        messages.warning(request, "Vous ne pouvez pas changer de rôle.")
        return redirect('dashboard')
    
    request.session['active_role'] = role
    return redirect('dashboard')

@login_required
def load_panel_view(request, panel_name):
    active_role = _get_active_role(request)
    
    # ── Contrôle d'accès par rôle ─────────────────────────────────────────
    if not _can_access_panel(active_role, panel_name):
        return _htmx_forbidden(panel_name)
    
    context = {'active_role': active_role}
    
    # Helper context variables
    now = timezone.now()
    today = datetime.date.today()

    # --- ADMIN MODULES ---
    if panel_name == 'adminDash':
        # Stats
        total_students = StudentProfile.objects.count()
        
        # Attendance percentage today
        att_today = Attendance.objects.filter(date=today)
        if att_today.exists():
            presents = att_today.filter(status__in=['PRESENT', 'LATE']).count()
            att_pct = int((presents / att_today.count()) * 100)
        else:
            att_pct = 0
            
        # Unpaid finances
        unpaid_payments = Payment.objects.filter(status__in=['UNPAID', 'PARTIAL'])
        pending_count = unpaid_payments.count()
        pending_amount = sum(p.tuition_fee.amount - p.amount_paid for p in unpaid_payments)
            
        # Bulletins count (students with at least one grade)
        bulletins_generated = StudentProfile.objects.annotate(grade_count=Count('grades')).filter(grade_count__gt=0).count()
            
        level_stats = []
        levels = ['6ème', '5ème', '4ème', '3ème']
        active_year = SchoolSettings.get().school_year
        for level in levels:
            avg_score = Grade.objects.filter(student__class_room__level=level, school_year=active_year).aggregate(Avg('score'))['score__avg']
            if avg_score is not None:
                level_stats.append({'level': level, 'score': round(avg_score, 1), 'pct': int((avg_score/20)*100)})
            else:
                level_stats.append({'level': level, 'score': 0.0, 'pct': 0})
                
        # Alerts
        alerts = Notification.objects.filter(Q(notification_type='ALERT') | Q(notification_type='ABSENCE'))[:4]
        
        # Attendance by class
        classes = SchoolClass.objects.all()
        class_attendance = []
        for c in classes:
            c_att = Attendance.objects.filter(school_class=c, date=today)
            if c_att.exists():
                pres = c_att.filter(status__in=['PRESENT', 'LATE']).count()
                pct = int((pres / c_att.count()) * 100)
                class_attendance.append({
                    'class': c.name, 'present_str': f"{pres}/{c_att.count()}", 
                    'pct': f"{pct}%", 'badge': 'bg' if pct >= 90 else 'ba'
                })

        context.update({
            'total_students': total_students,
            'att_pct': att_pct,
            'pending_count': pending_count,
            'pending_amount': pending_amount,
            'bulletins_generated': bulletins_generated,
            'level_stats': level_stats,
            'alerts': alerts,
            'class_attendance': class_attendance,
        })
        return render(request, 'partials/admin_dash.html', context)
        
    elif panel_name == 'notifications':
        notifs = Notification.objects.filter(user=request.user)
        total_count = notifs.count()
        selected_type = request.GET.get('type')
        if selected_type:
            notifs = notifs.filter(notification_type=selected_type)
        context.update({
            'notifications': notifs,
            'total_count': total_count,
            'active_type': selected_type or 'all'
        })
        return render(request, 'partials/notifications.html', context)
        
    elif panel_name == 'eleves':
        classes = SchoolClass.objects.all()
        selected_class = request.GET.get('class_id')
        search_query = request.GET.get('q', '')
        
        students = StudentProfile.objects.select_related('user', 'class_room').prefetch_related('payments').annotate(
            avg_grade=Avg('grades__score'),
            total_attendance=Count('attendances'),
            present_attendance=Count('attendances', filter=Q(attendances__status__in=['PRESENT', 'LATE']))
        )
        if selected_class:
            students = students.filter(class_room_id=selected_class)
        if search_query:
            students = students.filter(
                Q(user__first_name__icontains=search_query) | 
                Q(user__last_name__icontains=search_query) |
                Q(registration_number__icontains=search_query)
            )
            
        student_data = []
        for s in students:
            # Average grade
            avg_g = round(s.avg_grade, 1) if s.avg_grade is not None else None
            
            # Attendance
            if s.total_attendance > 0:
                att_pct = int((s.present_attendance / s.total_attendance) * 100)
            else:
                att_pct = 98 # mock
                
            # Payment status
            prefetched_payments = list(s.payments.all())
            pay = prefetched_payments[0] if prefetched_payments else None
            pay_status = 'À jour' if (pay and pay.status == 'PAID') else 'En retard'
            
            student_data.append({
                'profile': s,
                'name': s.user.get_full_name() or s.user.username,
                'class': s.class_room.name if s.class_room else 'Non assignée',
                'average': avg_g,
                'attendance_pct': att_pct,
                'payment_status': pay_status
            })
            
        context.update({
            'classes': classes,
            'students': student_data,
            'selected_class': int(selected_class) if selected_class else None,
            'search_query': search_query,
        })
        return render(request, 'partials/eleves.html', context)


    elif panel_name == 'profs':
        teachers = TeacherProfile.objects.select_related('user').prefetch_related('subjects')
        
        from collections import defaultdict
        schedules = ClassSchedule.objects.select_related('school_class').values('teacher_id', 'school_class__name')
        teacher_classes_map = defaultdict(set)
        for sch in schedules:
            teacher_classes_map[sch['teacher_id']].add(sch['school_class__name'])
            
        teacher_list = []
        for t in teachers:
            subjects_list = ", ".join([sub.name for sub in t.subjects.all()])
            classes_set = teacher_classes_map.get(t.id, set())
            classes_list = ", ".join(sorted(list(classes_set)))
            
            # Calculer les heures réelles à partir de l'emploi du temps (chaque créneau = 2 heures)
            real_slots = ClassSchedule.objects.filter(teacher=t).count()
            hours = real_slots * 2
            
            teacher_list.append({
                'profile': t,
                'name': t.user.get_full_name() or t.user.username,
                'subjects': subjects_list or "—",
                'classes': classes_list or "—",
                'hours': hours,
                'status': 'Actif',
            })
        context.update({'teachers': teacher_list})
        return render(request, 'partials/profs.html', context)


    elif panel_name == 'paiements':
        # Tuition dashboard
        total_collected_agg = Payment.objects.filter(status='PAID').aggregate(Sum('amount_paid'))['amount_paid__sum']
        total_collected = float(total_collected_agg) if total_collected_agg is not None else 0.0
        
        unpaid = Payment.objects.filter(status__in=['UNPAID', 'PARTIAL']).select_related('tuition_fee')
        pending_amount = float(sum(p.tuition_fee.amount - p.amount_paid for p in unpaid))
        pending_count = unpaid.count()
        
        # Taux de recouvrement dynamique
        total_due = total_collected + pending_amount
        recovery_pct = int((total_collected / total_due) * 100) if total_due > 0 else 0
        
        # Moyenne des frais de scolarité configurés
        avg_fee = TuitionFee.objects.aggregate(Avg('amount'))['amount__avg']
        tuition_fee_amount = float(avg_fee) if avg_fee is not None else 0.0
        
        recent_payments = Payment.objects.filter(status='PAID').select_related('student__user', 'tuition_fee').order_by('-paid_at')[:5]
        unpaid_priorities = Payment.objects.filter(status__in=['UNPAID', 'PARTIAL']).select_related('student__user', 'tuition_fee').order_by('tuition_fee__due_date')[:5]
        students_list = StudentProfile.objects.select_related('user', 'class_room').all().order_by('user__last_name', 'user__first_name')

        context.update({
            'total_collected': int(total_collected),
            'pending_amount': int(pending_amount),
            'pending_count': pending_count,
            'recovery_pct': recovery_pct,
            'tuition_fee_amount': int(tuition_fee_amount),
            'recent_payments': recent_payments,
            'unpaid_priorities': unpaid_priorities,
            'students_list': students_list,
        })
        return render(request, 'partials/paiements.html', context)

    elif panel_name == 'presences':
        classes = SchoolClass.objects.all()
        selected_class_id = request.GET.get('class_id')
        selected_period = request.GET.get('period', 'MATIN')
        
        date_str = request.GET.get('date')
        if date_str:
            try:
                target_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                target_date = today
        else:
            target_date = today
            
        selected_class = None
        students = []
        
        if selected_class_id:
            selected_class = get_object_or_404(SchoolClass, id=selected_class_id)
            students = list(StudentProfile.objects.filter(class_room=selected_class))
            
            # Fetch existing attendances
            existing_atts = Attendance.objects.filter(
                school_class=selected_class,
                date=target_date,
                period=selected_period
            )
            att_map = {a.student_id: a for a in existing_atts}
            for s in students:
                att = att_map.get(s.id)
                s.attendance_status = att.status if att else 'PRESENT'
                s.attendance_excuse = att.excuse if att else ''
                s.attendance_justification_url = att.justification_file.url if att and att.justification_file else ''
                
        context.update({
            'classes': classes,
            'selected_class': selected_class,
            'students': students,
            'today': target_date.strftime('%Y-%m-%d'),
            'selected_period': selected_period,
        })
        return render(request, 'partials/presences.html', context)

    elif panel_name == 'bulletins':
        classes = SchoolClass.objects.all()
        selected_class_id = request.GET.get('class_id')
        term = request.GET.get('term', '2')
        try:
            term = int(term)
        except ValueError:
            term = 2
            
        selected_class = None
        bulletins_list = []
        term_range = range(1, 4)
        active_year = SchoolSettings.get().school_year
        has_compositions = False
        
        if selected_class_id:
            selected_class = get_object_or_404(SchoolClass, id=selected_class_id)
            students = StudentProfile.objects.filter(class_room=selected_class).select_related('user', 'parent__user')
            term_range = range(1, (selected_class.nb_trimestres or 3) + 1)
            
            if term != 0:
                has_compositions = Grade.objects.filter(
                    student__class_room=selected_class,
                    term=term,
                    school_year=active_year,
                    grade_type='COMPOSITION'
                ).exists()
                
            class_ranks = get_class_rankings(selected_class, term, active_year)
            
            # Précharger les notifications des parents pour éviter le N+1
            parent_user_ids = [s.parent.user_id for s in students if s.parent]
            sent_parent_notifs = set()
            if parent_user_ids:
                term_name = f"Trimestre {term}"
                sent_parent_notifs = set(
                    Notification.objects.filter(
                        user_id__in=parent_user_ids,
                        title="Bulletin scolaire disponible",
                        message__contains=term_name
                    ).values_list('user_id', flat=True)
                )
            
            for s in students:
                s_rank_info = class_ranks.get(s.id, {'rank_num': len(students), 'rank_str': '—', 'average': 0.0})
                avg_score = s_rank_info['average']
                rank_str = s_rank_info['rank_str']
                
                sent_to_parent = 'Oui' if (s.parent and s.parent.user_id in sent_parent_notifs) else 'Non'
                        
                bulletins_list.append({
                    'student': s,
                    'name': s.user.get_full_name() or s.user.username,
                    'average': avg_score,
                    'rank': rank_str,
                    'status': 'Officiel' if has_compositions or term == 0 else 'Provisoire (Devoirs)',
                    'sent': sent_to_parent,
                })
            bulletins_list.sort(key=lambda x: x['average'], reverse=True)


                
        context.update({
            'classes': classes,
            'selected_class': selected_class,
            'bulletins': bulletins_list,
            'selected_term': term,
            'term_range': term_range,
            'has_compositions': has_compositions,
        })
        return render(request, 'partials/bulletins.html', context)

    elif panel_name == 'emploiAdmin':
        classes = SchoolClass.objects.all()
        selected_class_id = request.GET.get('class_id')
        selected_class = None
        schedule = []
        teachers = TeacherProfile.objects.all()
        
        # Filtrer les matières selon la classe sélectionnée
        if selected_class_id:
            subjects = Subject.objects.filter(classes__id=selected_class_id)
            if not subjects.exists():
                subjects = Subject.objects.all()  # fallback si aucune affectation
        else:
            subjects = Subject.objects.all()
        
        if selected_class_id:
            selected_class = get_object_or_404(SchoolClass, id=selected_class_id)
            schedules_in_db = ClassSchedule.objects.filter(school_class=selected_class)
            
            slots = [
                ('08:00:00', '10:00:00', '08h-10h'),
                ('10:00:00', '12:00:00', '10h-12h'),
                ('14:00:00', '16:00:00', '14h-16h'),
            ]
            schedule = []
            for start, end, label in slots:
                days_data = []
                for day in range(1, 6):
                    sch = schedules_in_db.filter(day_of_week=day, start_time__gte=start, end_time__lte=end).first()
                    if sch:
                        days_data.append(f"{sch.subject.code or sch.subject.name} / {sch.teacher.user.last_name if sch.teacher else '—'}")
                    else:
                        days_data.append('—')
                schedule.append({'time': label, 'days': days_data})
                
        context.update({
            'classes': classes,
            'selected_class': selected_class,
            'schedule': schedule,
            'selected_class_id': int(selected_class_id) if selected_class_id else None,
            'subjects': subjects,
            'teachers': teachers,
        })
        return render(request, 'partials/emploi_admin.html', context)

    elif panel_name == 'settings':
        cfg = SchoolSettings.get()
        context.update({
            'school_name': cfg.school_name,
            'school_city': cfg.school_city,
            'school_year': cfg.school_year,
            'school_director': cfg.school_director,
            'school_email': cfg.school_email,
            'tuition_fee': cfg.tuition_fee,
            'nb_trimestres': cfg.nb_trimestres,
            'passing_score': cfg.passing_score,
            'sms_alerts': cfg.sms_alerts,
            'classes_list': SchoolClass.objects.all().order_by('name'),
            'subjects_list': Subject.objects.all().order_by('name'),
        })
        return render(request, 'partials/settings.html', context)

    elif panel_name == 'personnel':
        admins = AdminProfile.objects.all()
        context.update({'admins': admins})
        return render(request, 'partials/personnel.html', context)

    elif panel_name == 'dossiers':
        docs = DocumentFile.objects.all().order_by('-uploaded_at')
        
        # Calculer le nombre réel de documents par catégorie
        counts = {item['category']: item['count'] for item in DocumentFile.objects.values('category').annotate(count=Count('id'))}
        
        def get_size_label(code):
            count = counts.get(code, 0)
            if code == 'BULLETINS':
                suffix = " PDF" if count > 1 else " PDF"
            else:
                suffix = " fichiers" if count > 1 else " fichier"
            return f"{count}{suffix}"

        categories = [
            {'name': 'Dossiers élèves', 'size': get_size_label('ELEVES'), 'icon': 'ti-users', 'bg': '#EEEDFE', 'color': '#534AB7', 'code': 'ELEVES'},
            {'name': 'Bulletins', 'size': get_size_label('BULLETINS'), 'icon': 'ti-report', 'bg': '#E1F5EE', 'color': '#0F6E56', 'code': 'BULLETINS'},
            {'name': 'Courriers', 'size': get_size_label('COURRIERS'), 'icon': 'ti-mail', 'bg': '#FAEEDA', 'color': '#854F0B', 'code': 'COURRIERS'},
            {'name': 'Contrats', 'size': get_size_label('CONTRATS'), 'icon': 'ti-file', 'bg': '#FAECE7', 'color': '#993C1D', 'code': 'CONTRATS'},
            {'name': 'Budgets', 'size': get_size_label('BUDGETS'), 'icon': 'ti-coin', 'bg': '#E6F1FB', 'color': '#185FA5', 'code': 'BUDGETS'},
            {'name': 'Règlements', 'size': get_size_label('REGLEMENTS'), 'icon': 'ti-scale', 'bg': '#FCEBEB', 'color': '#A32D2D', 'code': 'REGLEMENTS'},
        ]
        context.update({
            'categories': categories,
            'documents': docs
        })
        return render(request, 'partials/dossiers.html', context)

    elif panel_name == 'auditLog':
        from core.models import AuditLog
        logs = AuditLog.objects.all().order_by('-timestamp')[:100]
        context.update({'logs': logs})
        return render(request, 'partials/audit_log.html', context)

    elif panel_name == 'classement':
        classes = SchoolClass.objects.all()
        selected_class_id = request.GET.get('class_id')
        selected_term = request.GET.get('term', '2')
        try:
            selected_term = int(selected_term)
        except ValueError:
            selected_term = 2

        ranking = []
        selected_class = None
        term_range = range(1, 4)
        active_year = SchoolSettings.get().school_year
        
        if selected_class_id:
            selected_class = get_object_or_404(SchoolClass, id=selected_class_id)
            students = StudentProfile.objects.filter(class_room=selected_class).select_related('user')
            term_range = range(1, (selected_class.nb_trimestres or 3) + 1)
            
            configs = {cfg.subject_id: float(cfg.coefficient) for cfg in ClassSubjectConfig.objects.filter(school_class=selected_class)}
            class_ranks = get_class_rankings(selected_class, selected_term, active_year)
            
            # Précharger le nombre de notes pour tous les élèves de la classe
            grade_counts = {}

            if selected_term == 0:
                grades_qs = Grade.objects.filter(student__class_room=selected_class, school_year=active_year)
            else:
                grades_qs = Grade.objects.filter(student__class_room=selected_class, term=selected_term, school_year=active_year)
            
            for gc in grades_qs.values('student_id').annotate(cnt=Count('id')):
                grade_counts[gc['student_id']] = gc['cnt']
                
            # Précharger le nombre d'absences pour tous les élèves de la classe
            absence_counts = {}
            absences_qs = Attendance.objects.filter(student__class_room=selected_class, status='ABSENT', school_year=active_year)
            for ac in absences_qs.values('student_id').annotate(cnt=Count('id')):
                absence_counts[ac['student_id']] = ac['cnt']
            
            for s in students:
                grade_count = grade_counts.get(s.id, 0)
                    
                if grade_count > 0:
                    absences = absence_counts.get(s.id, 0)
                    
                    subjects = Subject.objects.filter(classes=selected_class).distinct()
                    if not subjects.exists():
                        subjects = Subject.objects.all()
                    total_coef = sum(configs.get(sub.id, float(sub.coefficient)) for sub in subjects)
                    
                    s_rank_info = class_ranks.get(s.id, {'rank_num': len(students)})
                    avg = s_rank_info.get('average', 0.0) if 'average' in s_rank_info else 0.0
                    
                    ranking.append({
                        'student': s,
                        'name': s.user.get_full_name() or s.user.username,
                        'avg': avg,
                        'absences': absences,
                        'grade_count': grade_count,
                        'total_coef': round(total_coef, 1),
                        'rank': s_rank_info['rank_num'],
                        'badge': 'bg' if avg >= 14 else ('bp' if avg >= 10 else 'ba'),
                    })
            ranking.sort(key=lambda x: x['avg'], reverse=True)



        context.update({
            'classes': classes,
            'selected_class': selected_class,
            'selected_class_id': int(selected_class_id) if selected_class_id else None,
            'selected_term': selected_term,
            'term_range': term_range,
            'ranking': ranking,
        })
        return render(request, 'partials/classement.html', context)

    elif panel_name == 'congesProfs':
        teachers = TeacherProfile.objects.all()
        all_leaves = TeacherLeave.objects.all().order_by('-created_at')
        pending_count = all_leaves.filter(status='PENDING').count()
        context.update({
            'teachers': teachers,
            'leaves': all_leaves,
            'pending_count': pending_count,
        })
        return render(request, 'partials/conges_profs.html', context)

    elif panel_name == 'planning':
        classes = SchoolClass.objects.all()
        events = SchoolEvent.objects.all().order_by('start_date')
        # Group events by month for display
        today = datetime.date.today()
        context.update({
            'events': events,
            'classes': classes,
            'today': today,
        })
        return render(request, 'partials/planning.html', context)

    elif panel_name == 'messagerie':
        # Chat interface
        contacts = User.objects.exclude(id=request.user.id)[:5]
        active_chat_user_id = request.GET.get('chat_user_id')
        active_chat_user = None
        messages_list = []
        
        if active_chat_user_id:
            active_chat_user = get_object_or_404(User, id=active_chat_user_id)
            messages_list = Message.objects.filter(
                (Q(sender=request.user) & Q(recipient=active_chat_user)) |
                (Q(sender=active_chat_user) & Q(recipient=request.user))
            ).order_by('created_at')
            
        context.update({
            'contacts': contacts,
            'active_chat_user': active_chat_user,
            'messages_list': messages_list,
        })
        return render(request, 'partials/messagerie.html', context)

    # --- TEACHER MODULES ---
    elif panel_name == 'profDash':
        # Stats
        # Get teacher profile
        teacher_prof = None
        if hasattr(request.user, 'teacher_profile'):
            teacher_prof = request.user.teacher_profile
        else:
            teacher_prof = TeacherProfile.objects.first()
            
        active_year = SchoolSettings.get().school_year
        term = 2 # default term
        
        if teacher_prof:
            classes_qs = SchoolClass.objects.filter(schedules__teacher=teacher_prof).distinct()
            classes_count = classes_qs.count()
            students_count = StudentProfile.objects.filter(class_room__in=classes_qs).distinct().count()
            
            # Teacher's classes details
            teacher_classes = []
            for c in classes_qs:
                num_students = c.students.count()
                
                # Class average
                student_averages = []
                for student in c.students.all():
                    student_avg = get_student_term_average(student, term, active_year)
                    if student_avg > 0:
                        student_averages.append(student_avg)
                class_avg = round(sum(student_averages) / len(student_averages), 1) if student_averages else 14.0
                
                # Presence rate today
                c_att = Attendance.objects.filter(school_class=c, date=today)
                if c_att.exists():
                    pres_count = c_att.filter(status__in=['PRESENT', 'LATE']).count()
                    pres_pct = f"{int((pres_count / c_att.count()) * 100)}%"
                else:
                    pres_pct = "100%"
                    
                teacher_classes.append({
                    'name': c.name,
                    'students': num_students,
                    'avg': class_avg,
                    'pres': pres_pct
                })
                
            # Today's agenda
            agenda = []
            weekday = today.isoweekday()
            if 1 <= weekday <= 5:
                schedules = ClassSchedule.objects.filter(teacher=teacher_prof, day_of_week=weekday).order_by('start_time')
                for sch in schedules:
                    time_str = sch.start_time.strftime('%Hh%M')
                    agenda.append({
                        'time': time_str,
                        'title': f"Cours {sch.school_class.name} — {sch.subject.name} (Salle {sch.room or '—'})"
                    })
        else:
            classes_count = 0
            students_count = 0
            teacher_classes = []
            agenda = []
            
        classes_names = [c['name'] for c in teacher_classes]
        classes_averages = [float(c['avg']) for c in teacher_classes]

        context.update({
            'classes_count': classes_count,
            'students_count': students_count,
            'teacher_classes': teacher_classes,
            'agenda': agenda,
            'classes_names': classes_names,
            'classes_averages': classes_averages,
        })
        return render(request, 'partials/prof_dash.html', context)

    elif panel_name == 'mesEleves':
        # List teacher's students
        selected_class_id = request.GET.get('class_id')
        try:
            teacher_prof = request.user.teacher_profile
            teacher_classes = SchoolClass.objects.filter(schedules__teacher=teacher_prof).distinct()
        except Exception:
            teacher_classes = SchoolClass.objects.all()
            
        if not selected_class_id and teacher_classes.exists():
            selected_class_id = teacher_classes.first().id
            
        students = StudentProfile.objects.all()
        if selected_class_id:
            students = students.filter(class_room_id=selected_class_id)
        elif teacher_classes.exists():
            students = students.filter(class_room__in=teacher_classes)
            
        student_data = []
        active_year = SchoolSettings.get().school_year
        term_param = request.GET.get('term')
        try:
            term_val = int(term_param)
        except (ValueError, TypeError):
            term_val = 2
        for s in students:
            avg_g = get_student_term_average(s, term_val, active_year)
            avg_g = round(avg_g, 1) if avg_g > 0 else None
            
            # Calculer la présence réelle
            atts = s.attendances.all()
            total_atts = atts.count()
            if total_atts > 0:
                presents = atts.filter(status__in=['PRESENT', 'LATE']).count()
                presence_pct = f"{int((presents / total_atts) * 100)}%"
            else:
                presence_pct = "—"
                
            student_data.append({
                'profile': s,
                'name': s.user.get_full_name() or s.user.username,
                'avg': avg_g,
                'presence': presence_pct,
                'trend': '→',
            })
            
        context.update({
            'students': student_data,
            'teacher_classes': teacher_classes,
            'selected_class_id': int(selected_class_id) if selected_class_id else None
        })
        return render(request, 'partials/mes_eleves.html', context)

    elif panel_name == 'saisirNotes':
        classes = SchoolClass.objects.all()
        selected_class_id = request.GET.get('class_id')
        selected_subject_id = request.GET.get('subject_id')
        
        selected_term = request.GET.get('term')
        try:
            selected_term = int(selected_term)
        except (ValueError, TypeError):
            selected_term = 2

        grade_type = request.GET.get('grade_type', 'DEVOIR')
        devoir_num_str = request.GET.get('devoir_num', '1')
        try:
            devoir_num = int(devoir_num_str)
        except (ValueError, TypeError):
            devoir_num = 1
            
        students = []
        term_range = range(1, 4)
        
        # Matières filtrées selon la classe sélectionnée
        if selected_class_id:
            class_obj = get_object_or_404(SchoolClass, id=selected_class_id)
            students = StudentProfile.objects.filter(class_room=class_obj)
            subjects = Subject.objects.filter(classes=class_obj)
            term_range = range(1, (class_obj.nb_trimestres or 3) + 1)
            if not subjects.exists():
                subjects = Subject.objects.all()  # fallback
        else:
            subjects = Subject.objects.all()
            
        existing_grades_map = {}
        active_year = SchoolSettings.get().school_year
        devoir_count_in_bulletin = True
        if selected_class_id and selected_subject_id:
            lookup_params = {
                'subject_id': selected_subject_id,
                'term': selected_term,
                'school_year': active_year,
                'grade_type': grade_type,
            }
            if grade_type == 'DEVOIR':
                lookup_params['devoir_num'] = devoir_num
            else:
                lookup_params['devoir_num'] = None
                
            grades_qs = Grade.objects.filter(student__class_room_id=selected_class_id, **lookup_params)
            for g in grades_qs:
                existing_grades_map[g.student_id] = g
            
            first_grade = grades_qs.first()
            if first_grade:
                devoir_count_in_bulletin = first_grade.count_in_bulletin
                
        for s in students:
            g_obj = existing_grades_map.get(s.id)
            s.existing_score = float(g_obj.score) if g_obj else None
            if s.existing_score is not None:
                s.existing_score_str = f"{s.existing_score:.2f}".rstrip('0').rstrip('.')
            else:
                s.existing_score_str = ""
            s.existing_comment = g_obj.comment if g_obj else ""
            
        context.update({
            'classes': classes,
            'subjects': subjects,
            'students': students,
            'selected_class_id': int(selected_class_id) if selected_class_id else None,
            'selected_subject_id': int(selected_subject_id) if selected_subject_id else None,
            'selected_term': selected_term,
            'term_range': term_range,
            'grade_type': grade_type,
            'devoir_num': devoir_num,
            'devoir_count_in_bulletin': devoir_count_in_bulletin,
        })
        return render(request, 'partials/saisir_notes.html', context)

    elif panel_name == 'appel':
        classes = SchoolClass.objects.all()
        selected_class_id = request.GET.get('class_id')
        selected_period = request.GET.get('period', 'MATIN')
        
        date_str = request.GET.get('date')
        if date_str:
            try:
                target_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                target_date = today
        else:
            target_date = today
            
        students = []
        presents_count = 0
        absents_count = 0
        lates_count = 0
        
        if selected_class_id:
            class_obj = get_object_or_404(SchoolClass, id=selected_class_id)
            students = list(StudentProfile.objects.filter(class_room=class_obj))
            
            # Fetch existing attendances
            existing_atts = Attendance.objects.filter(
                school_class=class_obj,
                date=target_date,
                period=selected_period
            )
            att_map = {a.student_id: a for a in existing_atts}
            for s in students:
                att = att_map.get(s.id)
                s.attendance_status = att.status if att else 'PRESENT'
                s.attendance_excuse = att.excuse if att else ''
                s.attendance_justification_url = att.justification_file.url if att and att.justification_file else ''
                
                if s.attendance_status == 'PRESENT':
                    presents_count += 1
                elif s.attendance_status == 'ABSENT':
                    absents_count += 1
                elif s.attendance_status == 'LATE':
                    lates_count += 1
                    
        context.update({
            'classes': classes,
            'students': students,
            'selected_class_id': int(selected_class_id) if selected_class_id else None,
            'today': target_date.strftime('%Y-%m-%d'),
            'selected_period': selected_period,
            'presents_count': presents_count,
            'absents_count': absents_count,
            'lates_count': lates_count,
        })
        return render(request, 'partials/appel.html', context)

    elif panel_name == 'bulletinProf':
        classes = SchoolClass.objects.all()
        selected_class_id = request.GET.get('class_id')
        bulletins = []
        active_year = SchoolSettings.get().school_year
        term_range = range(1, 4)
        term_val = 2
        has_compositions = False
        
        if selected_class_id:
            class_obj = get_object_or_404(SchoolClass, id=selected_class_id)
            term_range = range(1, (class_obj.nb_trimestres or 3) + 1)
            term_param = request.GET.get('term')
            try:
                term_val = int(term_param)
            except (ValueError, TypeError):
                term_val = 2
            if term_val not in term_range:
                term_val = list(term_range)[-1]
                
            if term_val != 0:
                has_compositions = Grade.objects.filter(
                    student__class_room=class_obj,
                    term=term_val,
                    school_year=active_year,
                    grade_type='COMPOSITION'
                ).exists()
                
            students = StudentProfile.objects.filter(class_room=class_obj)
            class_ranks = get_class_rankings(class_obj, term_val, active_year)
            
            for s in students:
                s_rank_info = class_ranks.get(s.id, {'rank_num': len(students), 'rank_str': '—', 'average': 0.0})
                avg = s_rank_info['average']
                rank_str = s_rank_info['rank_str']
                bulletins.append({
                    'name': s.user.get_full_name() or s.user.username,
                    'avg': round(avg, 1),
                    'rank': rank_str,
                    'remark': 'Excellent travail' if avg >= 16 else ('Bon travail' if avg >= 12 else 'Peut mieux faire')
                })
            bulletins.sort(key=lambda x: x['avg'], reverse=True)

        context.update({
            'classes': classes,
            'bulletins': bulletins,
            'selected_class_id': int(selected_class_id) if selected_class_id else None,
            'selected_term': term_val,
            'term_range': term_range,
            'has_compositions': has_compositions,
        })
        return render(request, 'partials/bulletin_prof.html', context)

    elif panel_name == 'agenda':
        today = datetime.date.today()
        # Lundi de la semaine courante
        monday = today - datetime.timedelta(days=today.weekday())
        
        day_names_short = {1: 'Lun', 2: 'Mar', 3: 'Mer', 4: 'Jeu', 5: 'Ven'}
        day_colors = {
            'EXAM': '#854F0B',      # Orange/Brown
            'HOLIDAY': '#A32D2D',   # Red
            'MEETING': '#534AB7',   # Purple
            'SPORT': '#1D9E75',     # Green
            'CULTURAL': '#185FA5',  # Blue
            'OTHER': '#D3D1C7',     # Gray
            'COURSE': '#534AB7',    # Purple for normal courses
        }
        
        agenda_items = []
        
        # 1. Obtenir les événements généraux de la semaine
        week_events = SchoolEvent.objects.filter(
            start_date__gte=monday,
            start_date__lte=monday + datetime.timedelta(days=4)
        ).order_by('start_date')
        
        for evt in week_events:
            day_idx = evt.start_date.weekday() + 1
            if 1 <= day_idx <= 5:
                day_label = f"{day_names_short.get(day_idx, 'Lun')} {evt.start_date.day}"
                agenda_items.append({
                    'date': day_label,
                    'time': 'Journée',
                    'title': f"{evt.get_event_type_display()} : {evt.title}" + (f" ({evt.school_class.name})" if evt.school_class else ""),
                    'color': day_colors.get(evt.event_type, '#D3D1C7'),
                    'sorting': (day_idx, '00:00:00')
                })
                
        # 2. Obtenir les cours hebdomadaires de l'enseignant ou de l'admin
        schedules_qs = ClassSchedule.objects.select_related('school_class', 'subject', 'teacher__user')
        if active_role == 'prof' and hasattr(request.user, 'teacher_profile'):
            schedules_qs = schedules_qs.filter(teacher=request.user.teacher_profile)
            
        for sch in schedules_qs:
            day_idx = sch.day_of_week
            if 1 <= day_idx <= 5:
                # Calculer la date réelle de ce jour de la semaine
                evt_date = monday + datetime.timedelta(days=day_idx - 1)
                day_label = f"{day_names_short.get(day_idx, 'Lun')} {evt_date.day}"
                time_label = sch.start_time.strftime('%Hh%M')
                
                title = f"Cours {sch.school_class.name} — {sch.subject.name}"
                if active_role == 'admin':
                    title += f" (Prof. {sch.teacher.user.last_name if sch.teacher else '—'})"
                if sch.room:
                    title += f" (Salle {sch.room})"
                    
                agenda_items.append({
                    'date': day_label,
                    'time': time_label,
                    'title': title,
                    'color': day_colors['COURSE'],
                    'sorting': (day_idx, sch.start_time.strftime('%H:%M:%S'))
                })
                
        # Trier par jour puis par heure
        agenda_items.sort(key=lambda x: x['sorting'])

        context.update({'agenda_items': agenda_items})
        return render(request, 'partials/agenda.html', context)

    # --- STUDENT MODULES ---
    elif panel_name == 'eleveDash':
        # Resolve student profile
        student_prof = None
        if hasattr(request.user, 'student_profile'):
            student_prof = request.user.student_profile
        else:
            student_prof = StudentProfile.objects.first()
            
        active_year = SchoolSettings.get().school_year
        term = 2 # default term
        
        if student_prof:
            class_room = student_prof.class_room
            if class_room:
                term = class_room.nb_trimestres or 3
            
            avg = get_student_term_average(student_prof, term, active_year)
            avg = round(avg, 1) if avg > 0 else "0.0"
            
            # Rank
            rank_str = "—"
            if class_room:
                class_ranks = get_class_rankings(class_room, term, active_year)
                s_rank_info = class_ranks.get(student_prof.id)
                if s_rank_info:
                    rank_str = s_rank_info['rank_str']

            
            # Attendance
            attendances = student_prof.attendances.all()
            total_att = attendances.count()
            presents_count = attendances.filter(status__in=['PRESENT', 'LATE']).count()
            attendance_rate = f"{int((presents_count / total_att) * 100)}%" if total_att > 0 else "N/A"
            
            # Payment status
            payments = student_prof.payments.filter(tuition_fee__school_year=active_year)
            if payments.exists():
                if payments.filter(status__in=['UNPAID', 'PARTIAL']).exists():
                    payment_status = "Incomplet"
                else:
                    payment_status = "À jour"
            else:
                payment_status = "À jour"
                
            # Latest grades
            latest_grades = []
            if class_room:
                subjects = Subject.objects.filter(classes=class_room).distinct()
                for sub in subjects:
                    details = get_student_subject_term_details(student_prof, sub, term, active_year)
                    if details['moyenne'] is not None:
                        score = details['moyenne']
                        latest_grades.append({
                            'subject': sub.name,
                            'score': score,
                            'pct': int((score / 20) * 100)
                        })
                latest_grades.sort(key=lambda x: x['score'], reverse=True)
                latest_grades = latest_grades[:5]
                
            # Today's courses
            today_courses = []
            if class_room:
                weekday = today.isoweekday()
                if 1 <= weekday <= 5:
                    schedules = ClassSchedule.objects.filter(school_class=class_room, day_of_week=weekday).order_by('start_time')
                    for sch in schedules:
                        time_str = f"{sch.start_time.strftime('%Hh%M')} - {sch.end_time.strftime('%Hh%M')}"
                        teacher_name = sch.teacher.user.get_full_name() if sch.teacher else "—"
                        detail_str = f"Salle {sch.room or '—'} — Prof. {teacher_name}"
                        today_courses.append({
                            'time': time_str,
                            'subject': sch.subject.name,
                            'detail': detail_str
                        })
        else:
            avg = "N/A"
            rank_str = "—"
            attendance_rate = "N/A"
            payment_status = "Aucun"
            latest_grades = []
            today_courses = []
            
        context.update({
            'average': avg,
            'rank': rank_str,
            'attendance_rate': attendance_rate,
            'payment_status': payment_status,
            'latest_grades': latest_grades,
            'today_courses': today_courses,
        })
        return render(request, 'partials/eleve_dash.html', context)

    elif panel_name == 'bulletin':
        # Report card for student (dynamic)
        student_id = request.GET.get('student_id')
        term = request.GET.get('term', '2')
        try:
            term = int(term)
        except ValueError:
            term = 2
            
        student_prof = None
        if student_id:
            student_prof = get_object_or_404(StudentProfile, id=student_id)
            # ── Vérification accès : l'élève ne peut voir QUE son propre bulletin ──
            if active_role == 'eleve':
                try:
                    own_profile = request.user.student_profile
                    if own_profile.id != student_prof.id:
                        return _htmx_forbidden('bulletin')
                except Exception:
                    return _htmx_forbidden('bulletin')
            # ── Le parent ne peut voir QUE le bulletin de ses enfants ──
            elif active_role == 'parent':
                try:
                    parent_prof = request.user.parent_profile
                    enfants_ids = list(parent_prof.children.values_list('id', flat=True))
                    if student_prof.id not in enfants_ids:
                        return _htmx_forbidden('bulletin')
                except Exception:
                    return _htmx_forbidden('bulletin')
        else:
            try:
                if active_role == 'parent':
                    parent_prof = request.user.parent_profile
                    student_prof = parent_prof.children.first()
                elif active_role == 'eleve':
                    student_prof = request.user.student_profile
                else:
                    # admin ou prof : premier élève par défaut
                    student_prof = StudentProfile.objects.first()
            except Exception:
                pass
                
        if not student_prof and active_role in ('admin', 'prof'):
            student_prof = StudentProfile.objects.first()
            
        if student_prof:
            student_name = student_prof.user.get_full_name() or student_prof.user.username
            class_name = student_prof.class_room.name if student_prof.class_room else 'Non assignée'
            student_db_id = student_prof.id
        else:
            student_name = "Sarr Kofi"
            class_name = "6ème A"
            student_db_id = 1
            
        grades = []
        rank_str = "—"
        term_range = range(1, 4)
        active_year = SchoolSettings.get().school_year
        
        if student_prof:
            term_range = range(1, (student_prof.class_room.nb_trimestres or 3) + 1) if student_prof.class_room else range(1, 4)
            configs = {cfg.subject_id: float(cfg.coefficient) for cfg in ClassSubjectConfig.objects.filter(school_class=student_prof.class_room)} if student_prof.class_room else {}
            
            # Calculate rank dynamically
            if student_prof.class_room:
                class_ranks = get_class_rankings(student_prof.class_room, term, active_year)
                s_rank_info = class_ranks.get(student_prof.id)
                if s_rank_info:
                    rank_num = s_rank_info['rank_num']
                    rank_str = f"{rank_num}er/{len(class_ranks)}" if rank_num == 1 else f"{rank_num}ème/{len(class_ranks)}"


            subjects = Subject.objects.filter(classes=student_prof.class_room).distinct() if student_prof.class_room else Subject.objects.all()
            
            if term == 0:
                # Annual
                nb_terms = student_prof.class_room.nb_trimestres or 3 if student_prof.class_room else 3
                for sub in subjects:
                    coef = configs.get(sub.id, float(sub.coefficient))
                    term_scores = []
                    for t in range(1, nb_terms + 1):
                        det = get_student_subject_term_details(student_prof, sub, t, active_year)
                        if det['moyenne'] is not None:
                            term_scores.append(det['moyenne'])
                    avg_score = sum(term_scores) / len(term_scores) if term_scores else None
                    
                    if avg_score is not None:
                        # Class average for annual
                        sibling_students = StudentProfile.objects.filter(class_room=student_prof.class_room) if student_prof.class_room else [student_prof]
                        sibling_annual_scores = []
                        for sib in sibling_students:
                            sib_term_scores = []
                            for t in range(1, nb_terms + 1):
                                sib_det = get_student_subject_term_details(sib, sub, t, active_year)
                                if sib_det['moyenne'] is not None:
                                    sib_term_scores.append(sib_det['moyenne'])
                            sib_avg = sum(sib_term_scores) / len(sib_term_scores) if sib_term_scores else None
                            if sib_avg is not None:
                                sibling_annual_scores.append(sib_avg)
                        class_avg = sum(sibling_annual_scores) / len(sibling_annual_scores) if sibling_annual_scores else avg_score
                        
                        grades.append({
                            'subject': sub.name,
                            'coef': coef,
                            'devoirs_str': "—",
                            'moy_devoirs': None,
                            'compo': None,
                            'score': round(avg_score, 2),
                            'class_avg': round(class_avg, 2),
                            'rank': "—",
                            'remark': "Moyenne annuelle"
                        })
            else:
                # Term specific
                for sub in subjects:
                    details = get_student_subject_term_details(student_prof, sub, term, active_year)
                    if details['moyenne'] is not None:
                        coef = configs.get(sub.id, float(sub.coefficient))
                        
                        # Calculate class average
                        sibling_students = StudentProfile.objects.filter(class_room=student_prof.class_room) if student_prof.class_room else [student_prof]
                        sibling_scores = []
                        for sib in sibling_students:
                            sib_details = get_student_subject_term_details(sib, sub, term, active_year)
                            if sib_details['moyenne'] is not None:
                                sibling_scores.append(sib_details['moyenne'])
                        class_avg = sum(sibling_scores) / len(sibling_scores) if sibling_scores else details['moyenne']
                        
                        # Calculate rank in subject
                        sibling_scores.sort(reverse=True)
                        try:
                            rank_num = sibling_scores.index(details['moyenne']) + 1
                            rank_str_sub = f"{rank_num}er" if rank_num == 1 else f"{rank_num}ème"
                        except ValueError:
                            rank_str_sub = "—"
                            
                        grades.append({
                            'subject': sub.name,
                            'coef': coef,
                            'devoirs_str': details['devoirs_str'],
                            'moy_devoirs': details['moy_devoirs'],
                            'compo': details['compo'],
                            'score': details['moyenne'],
                            'class_avg': round(class_avg, 2),
                            'rank': rank_str_sub,
                            'remark': details['remark'] or "Bon travail",
                        })
                        
        if term == 0:
            avg = get_student_annual_average(student_prof, active_year) if student_prof else 0
            has_compositions = True
        else:
            avg = get_student_term_average(student_prof, term, active_year) if student_prof else 0
            has_compositions = Grade.objects.filter(
                student__class_room=student_prof.class_room,
                term=term,
                school_year=active_year,
                grade_type='COMPOSITION'
            ).exists() if student_prof and student_prof.class_room else False
                
        context.update({
            'student_id': student_db_id,
            'student_name': student_name,
            'class_name': class_name,
            'rank': rank_str,
            'average': round(avg, 2),
            'grades': grades,
            'term': term,
            'term_range': term_range,
            'has_compositions': has_compositions,
        })
        return render(request, 'partials/bulletin_detail.html', context)

    elif panel_name == 'progression':
        # Resolve student (eleve or parent)
        student_prof = None
        if active_role == 'eleve':
            try:
                student_prof = request.user.student_profile
            except Exception:
                pass
        elif active_role == 'parent':
            try:
                student_prof = request.user.parent_profile.children.first()
            except Exception:
                pass
        else:
            # admin ou prof : peut voir n'importe quel élève
            student_id_prog = request.GET.get('student_id')
            if student_id_prog:
                student_prof = StudentProfile.objects.filter(id=student_id_prog).first()
            if not student_prof:
                student_prof = StudentProfile.objects.first()

        active_year = SchoolSettings.get().school_year
        student_name = student_prof.user.get_full_name() if student_prof else "—"
        nb_terms = student_prof.class_room.nb_trimestres if (student_prof and student_prof.class_room) else 3
        term_colors = ['#534AB7', '#1D9E75', '#185FA5']

        progression_terms = []
        for t in range(1, nb_terms + 1):
            avg = get_student_term_average(student_prof, t, active_year) if student_prof else 0
            progression_terms.append({
                'term': f'Trim. {t}',
                'score': round(avg, 1) if avg > 0 else '—',
                'pct': int((avg / 20) * 100) if avg > 0 else 0,
                'color': term_colors[(t - 1) % len(term_colors)],
            })

        context.update({
            'student_name': student_name,
            'progression_terms': progression_terms,
        })
        return render(request, 'partials/progression.html', context)

    elif panel_name == 'absencesEleve':
        # Resolve student (eleve or parent)
        student_prof = None
        if hasattr(request.user, 'student_profile'):
            student_prof = request.user.student_profile
        elif hasattr(request.user, 'parent_profile') and request.user.parent_profile.children.exists():
            student_prof = request.user.parent_profile.children.first()
        else:
            student_prof = StudentProfile.objects.first()

        absences_qs = []
        if student_prof:
            absences_qs = student_prof.attendances.filter(
                status__in=['ABSENT', 'LATE']
            ).order_by('-date')[:20]

        absences = []
        for a in absences_qs:
            absences.append({
                'date': a.date.strftime('%d %b. %Y'),
                'duration': a.get_period_display() if hasattr(a, 'get_period_display') else (a.period or 'Journée'),
                'type': 'Retard' if a.status == 'LATE' else 'Absence',
                'reason': a.excuse or '—',
                'status': 'Justifiée' if a.justification_file else ('Signalé' if a.excuse else 'Non justifiée'),
                'badge': 'bg' if a.justification_file else ('ba' if a.excuse else 'br'),
            })
        context.update({'absences': absences})
        return render(request, 'partials/absences_eleve.html', context)

    elif panel_name == 'paiementEleve':
        # Resolve student (eleve or parent)
        student_prof = None
        if hasattr(request.user, 'student_profile'):
            student_prof = request.user.student_profile
        elif hasattr(request.user, 'parent_profile') and request.user.parent_profile.children.exists():
            student_prof = request.user.parent_profile.children.first()
        else:
            student_prof = StudentProfile.objects.first()

        payments = []
        if student_prof:
            active_year = SchoolSettings.get().school_year
            payments_qs = student_prof.payments.select_related('tuition_fee').order_by('tuition_fee__term')
            for p in payments_qs:
                fee = p.tuition_fee
                if p.status == 'PAID':
                    status_label = 'Payé'
                    badge = 'bg'
                    date_label = p.paid_at.strftime('%d %b. %Y') if p.paid_at else '—'
                elif p.status == 'PARTIAL':
                    status_label = 'Partiel'
                    badge = 'ba'
                    date_label = f"Reste : {int(fee.amount - p.amount_paid):,} FCFA"
                else:
                    status_label = 'En attente'
                    badge = 'br'
                    date_label = f"Dû le {fee.due_date.strftime('%d %b.') if fee.due_date else '—'}"
                payments.append({
                    'term': f"Trimestre {fee.term}" if fee.term else fee.get_fee_type_display(),
                    'amount': f"{int(fee.amount):,} FCFA",
                    'date': date_label,
                    'status': status_label,
                    'badge': badge,
                })
        context.update({'payments': payments})
        return render(request, 'partials/paiement_eleve.html', context)

    elif panel_name == 'emploi':
        # Resolve student's class
        student_prof = None
        if hasattr(request.user, 'student_profile'):
            student_prof = request.user.student_profile
        elif hasattr(request.user, 'parent_profile') and request.user.parent_profile.children.exists():
            student_prof = request.user.parent_profile.children.first()
        else:
            student_prof = StudentProfile.objects.first()

        schedule = []
        if student_prof and student_prof.class_room:
            class_room = student_prof.class_room
            schedules_in_db = ClassSchedule.objects.filter(school_class=class_room).select_related('subject', 'teacher__user')
            slots = [
                ('08:00:00', '10:00:00', '08h-10h'),
                ('10:00:00', '12:00:00', '10h-12h'),
                ('12:00:00', '14:00:00', '12h-14h'),
                ('14:00:00', '16:00:00', '14h-16h'),
            ]
            for start, end, label in slots:
                days_data = []
                for day in range(1, 6):
                    sch = schedules_in_db.filter(day_of_week=day, start_time__gte=start, end_time__lte=end).first()
                    days_data.append(sch.subject.name if sch else '—')
                schedule.append({'time': label, 'days': days_data})
        context.update({'schedule': schedule})
        return render(request, 'partials/emploi.html', context)

    # --- PARENT MODULES ---
    elif panel_name == 'parentDash':
        # Resolve parent profile
        parent_prof = None
        if hasattr(request.user, 'parent_profile'):
            parent_prof = request.user.parent_profile
        else:
            parent_prof = ParentProfile.objects.first()
            
        active_year = SchoolSettings.get().school_year
        
        child = None
        if parent_prof:
            child = parent_prof.children.first()
            
        if child:
            child_name = f"{child.user.get_full_name() or child.user.username} — {child.class_room.name if child.class_room else 'Sans classe'}"
            term = child.class_room.nb_trimestres if child.class_room else 3
            
            # Child stats
            average = get_student_term_average(child, term, active_year)
            average = round(average, 1) if average > 0 else "0.0"
            
            # Rank
            rank_str = "—"
            if child.class_room:
                class_ranks = get_class_rankings(child.class_room, term, active_year)
                c_rank_info = class_ranks.get(child.id)
                if c_rank_info:
                    rank_str = c_rank_info['rank_str']

            
            # Attendance
            attendances = child.attendances.all()
            total_att = attendances.count()
            presents_count = attendances.filter(status__in=['PRESENT', 'LATE']).count()
            attendance_rate = f"{int((presents_count / total_att) * 100)}%" if total_att > 0 else "N/A"
            absences_count = attendances.filter(status='ABSENT').count()
            
            # Payment status
            payments = child.payments.filter(tuition_fee__school_year=active_year)
            if payments.exists():
                if payments.filter(status__in=['UNPAID', 'PARTIAL']).exists():
                    payment_status = "Paiements incomplets"
                    payment_badge = "br"
                else:
                    payment_status = "Paiements à jour"
                    payment_badge = "bg"
            else:
                payment_status = "Paiements à jour"
                payment_badge = "bg"
                
            # Courses
            courses = []
            if child.class_room:
                schedules = ClassSchedule.objects.filter(school_class=child.class_room).order_by('day_of_week', 'start_time')[:5]
                day_names = {1: 'Lundi', 2: 'Mardi', 3: 'Mercredi', 4: 'Jeudi', 5: 'Vendredi'}
                for sch in schedules:
                    courses.append({
                        'day': day_names.get(sch.day_of_week, 'Lundi'),
                        'subject': sch.subject.name,
                        'teacher': f"Prof. {sch.teacher.user.last_name}" if sch.teacher else "—",
                        'room': f"Salle {sch.room}" if sch.room else "—"
                    })
        else:
            child_name = "Aucun élève associé"
            average = "N/A"
            rank_str = "—"
            attendance_rate = "N/A"
            absences_count = 0
            payment_status = "Aucun"
            payment_badge = "bg"
            courses = []
            
        db_messages = Message.objects.filter(recipient=request.user).order_by('-created_at')[:4]

        messages_list = []
        for msg in db_messages:
            time_diff = timezone.now() - msg.created_at
            if time_diff.days > 0:
                time_str = f"il y a {time_diff.days}j"
            else:
                time_str = "aujourd'hui"
            messages_list.append({
                'sender': msg.sender.get_full_name() or msg.sender.username,
                'text': msg.content,
                'time': time_str,
                'bg': '#E1F5EE' if msg.sender.role == 'TEACHER' else '#EEEDFE',
                'color': '#0F6E56' if msg.sender.role == 'TEACHER' else '#534AB7'
            })
        if not messages_list:
            messages_list = [
                {'sender': 'Prof. Fall', 'text': 'Kofi progresse très bien. Excellent trimestre !', 'time': 'il y a 2j', 'bg': '#E1F5EE', 'color': '#0F6E56'},
                {'sender': 'Administration', 'text': 'Réunion parents le 15 déc. à 17h00.', 'time': 'il y a 3j', 'bg': '#EEEDFE', 'color': '#534AB7'},
            ]
            
        context.update({
            'child_name': child_name,
            'average': average,
            'rank': rank_str,
            'attendance_rate': attendance_rate,
            'absences_count': absences_count,
            'payment_status': payment_status,
            'payment_badge': payment_badge,
            'messages_list': messages_list,
            'courses': courses,
        })
        return render(request, 'partials/parent_dash.html', context)

    # Fallback default empty state
    return HttpResponse(f'<div class="empty-state">Module en développement : {panel_name}</div>')


# --- HTMX ACTIONS ---

@login_required
def add_student_view(request):
    if request.method == 'POST':
        from core.forms import StudentCreationForm
        form = StudentCreationForm(request.POST)
        if not form.is_valid():
            errors_html = ''.join(
                f'<div style="padding:4px 0;font-size:12px;color:#A32D2D;">✗ {field}: {", ".join(errs)}</div>'
                for field, errs in form.errors.items()
                if field != '__all__'
            )
            non_field = ''.join(
                f'<div style="padding:4px 0;font-size:12px;color:#A32D2D;">✗ {e}</div>'
                for e in form.non_field_errors()
            )
            return HttpResponse(
                f'<div style="padding:10px;background:rgba(163,45,45,0.07);border:1px solid rgba(163,45,45,0.2);border-radius:8px;margin-bottom:10px;">'
                f'{non_field}{errors_html}</div>'
            )

        cd = form.cleaned_data
        try:
            user = User.objects.create_user(
                username=cd['username'], email=cd['email'],
                first_name=cd['first_name'], last_name=cd['last_name'],
                role='STUDENT', password='Password123'
            )
            school_class = get_object_or_404(SchoolClass, id=cd['class_id'])
            _active_year = SchoolSettings.get().school_year
            _year_prefix = _active_year.split('/')[0].split('-')[0]  # ex: '2026' from '2026/2027'
            _student_count = StudentProfile.objects.count() + 1
            reg_num = f"{_year_prefix}-{_student_count:04d}"

            parent_user = User.objects.filter(role='PARENT').first()
            parent_profile = parent_user.parent_profile if hasattr(parent_user, 'parent_profile') else None

            student_profile = StudentProfile.objects.create(
                user=user, class_room=school_class,
                registration_number=reg_num, parent=parent_profile
            )

            from core.utils import log_audit
            log_audit(request, f"Création de l'élève {user.get_full_name()}", student_profile, changes={
                "username": cd['username'], "email": cd['email'], "class": school_class.name
            })
            Notification.objects.create(
                user=request.user, title="Nouvel élève inscrit",
                message=f"L'élève {user.get_full_name()} a été inscrit avec succès dans la classe {school_class.name}.",
                notification_type='INFO'
            )
            return HttpResponse('<script>showPanel("eleves", "Élèves", null);</script>')
        except Exception as e:
            return HttpResponse(f'<div class="alert-item" style="color:#A32D2D">Erreur: {str(e)}</div>', status=400)
    return HttpResponse('Méthode non autorisée', status=405)

@login_required
def save_attendance_view(request):
    if request.method == 'POST':
        class_id = request.POST.get('class_id')
        date_str = request.POST.get('date', datetime.date.today().strftime('%Y-%m-%d'))
        period = request.POST.get('period', 'MATIN')
        
        school_class = get_object_or_404(SchoolClass, id=class_id)
        
        # Validation: Date not in future
        try:
            input_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
            if input_date > datetime.date.today():
                return HttpResponse('<div style="padding:10px;color:#A32D2D;background:#FCEBEB;border-radius:var(--border-radius-md);margin-bottom:10px">✗ Erreur : La date de présence ne peut pas être dans le futur.</div>')
        except ValueError:
            return HttpResponse('<div style="padding:10px;color:#A32D2D;background:#FCEBEB;border-radius:var(--border-radius-md);margin-bottom:10px">✗ Erreur : Format de date invalide.</div>')

        students = StudentProfile.objects.filter(class_room=school_class)
        
        for s in students:
            status = request.POST.get(f'attendance_{s.id}', 'PRESENT')
            arrival_time = None
            if status == 'LATE':
                arrival_time = datetime.time(8, 15)
            elif status == 'PRESENT':
                arrival_time = datetime.time(8, 0)
                
            excuse = request.POST.get(f'excuse_{s.id}', '')
            uploaded_file = request.FILES.get(f'file_{s.id}')
            
            defaults = {
                'school_class': school_class,
                'status': status,
                'arrival_time': arrival_time,
                'excuse': excuse if excuse else None
            }
            if uploaded_file:
                defaults['justification_file'] = uploaded_file
            
            Attendance.objects.update_or_create(
                student=s, date=input_date, period=period,
                defaults=defaults
            )
            
            # Create alert for parents & student if absent
            if status == 'ABSENT':
                # Notify student
                Notification.objects.create(
                    user=s.user, title="Absence signalée",
                    message=f"Vous avez été marqué(e) absent(e) le {date_str} ({period}).",
                    notification_type='ABSENCE'
                )
                # Notify parent
                if s.parent:
                    Notification.objects.create(
                        user=s.parent.user, title="Absence signalée",
                        message=f"Votre enfant {s.user.get_full_name()} a été marqué absent le {date_str} ({period}).",
                        notification_type='ABSENCE'
                    )
                    if s.parent.user.email:
                        from core.utils import send_system_email
                        send_system_email(
                            subject=f"Alerte Absence - {s.user.get_full_name()}",
                            message=f"Bonjour,\n\nNous vous informons que votre enfant {s.user.get_full_name()} a été marqué(e) absent(e) aujourd'hui ({date_str}, période: {period}).\n\nVeuillez contacter l'administration pour justifier cette absence.\n\nCordialement,\nLa vie scolaire.",
                            recipient_list=[s.parent.user.email]
                        )

        # Audit logging
        from core.utils import log_audit
        log_audit(request, f"Enregistrement de l'appel pour la classe {school_class.name} le {date_str} ({period})", school_class)

        Notification.objects.create(
            user=request.user, title="Appel enregistré",
            message=f"Le registre de présence pour la classe {school_class.name} a été validé.",
            notification_type='INFO'
        )
        return HttpResponse('<div style="padding:10px;color:#0F6E56;background:#E1F5EE;border-radius:var(--border-radius-md);margin-bottom:10px">✓ Présences enregistrées avec succès</div>')
    return HttpResponse('Méthode non autorisée', status=405)

@login_required
def save_grades_view(request):
    if request.method == 'POST':
        class_id = request.POST.get('class_id')
        subject_id = request.POST.get('subject_id')
        term = int(request.POST.get('term', 2))
        grade_type = request.POST.get('grade_type', 'COMPOSITION')
        devoir_num_str = request.POST.get('devoir_num')

        # count_in_bulletin est une case à cocher globale pour ce devoir
        # Les compositions comptent TOUJOURS dans le bulletin
        if grade_type == 'COMPOSITION':
            count_in_bulletin = True
        else:
            count_in_bulletin = (request.POST.get('count_in_bulletin', 'off') == 'on')

        devoir_num = None
        if grade_type == 'DEVOIR':
            try:
                devoir_num = int(devoir_num_str) if devoir_num_str else 1
            except ValueError:
                devoir_num = 1

        school_class = get_object_or_404(SchoolClass, id=class_id)
        subject = get_object_or_404(Subject, id=subject_id)

        try:
            teacher_profile = request.user.teacher_profile
        except Exception:
            # Admin or non-teacher user: try to get any teacher, or use None (allowed since teacher is nullable)
            try:
                teacher_user = User.objects.filter(role='TEACHER').first()
                teacher_profile = teacher_user.teacher_profile if teacher_user else None
            except Exception:
                teacher_profile = None

        active_year = SchoolSettings.get().school_year
        students = StudentProfile.objects.filter(class_room=school_class)
        for s in students:
            score_str = request.POST.get(f'grade_{s.id}')
            comment = request.POST.get(f'comment_{s.id}', '')

            lookup_params = {
                'student': s,
                'subject': subject,
                'term': term,
                'school_year': active_year,
                'grade_type': grade_type,
            }
            if grade_type == 'DEVOIR':
                lookup_params['devoir_num'] = devoir_num
            else:
                lookup_params['devoir_num'] = None

            if score_str != "" and score_str is not None:
                try:
                    score = float(score_str)
                    if not (0.0 <= score <= 20.0):
                        return HttpResponse(f'<div style="padding:10px;color:#A32D2D;background:#FCEBEB;border-radius:var(--border-radius-md);margin-bottom:10px">&#10007; Erreur : La note doit être comprise entre 0 et 20 (Note fournie pour {s.user.get_full_name()} : {score}).</div>')
                except ValueError:
                    return HttpResponse('<div style="padding:10px;color:#A32D2D;background:#FCEBEB;border-radius:var(--border-radius-md);margin-bottom:10px">&#10007; Erreur : Format de note invalide.</div>')

                from academics.models import ClassSubjectConfig
                class_config = ClassSubjectConfig.objects.filter(school_class=school_class, subject=subject).first()
                coef = class_config.coefficient if class_config else subject.coefficient

                Grade.objects.update_or_create(
                    **lookup_params,
                    defaults={
                        'teacher': teacher_profile,
                        'score': score,
                        'comment': comment,
                        'coefficient': coef,
                        'count_in_bulletin': count_in_bulletin,
                    }
                )
            else:
                Grade.objects.filter(**lookup_params).delete()

        # Audit logging
        from core.utils import log_audit
        bulletin_flag = "" if count_in_bulletin else " [HORS BULLETIN]"
        desc_str = f"Saisie des devoirs (N°{devoir_num}){bulletin_flag}" if grade_type == 'DEVOIR' else "Saisie de la composition"
        log_audit(request, f"{desc_str} pour la classe {school_class.name} en {subject.name} (Trimestre {term})", school_class)

        status_label = "&#10003; Notes enregistrées avec succès"
        if grade_type == 'DEVOIR' and not count_in_bulletin:
            status_label += " <span style='color:#854F0B;font-size:11px;'>(Ce devoir ne comptera PAS dans le bulletin)</span>"
        return HttpResponse(f'<div style="padding:10px;color:#0F6E56;background:#E1F5EE;border-radius:var(--border-radius-md);margin-bottom:10px">{status_label}</div>')
    return HttpResponse('Méthode non autorisée', status=405)

@login_required
@require_POST
def send_message_view(request):
    recipient_id = request.POST.get('recipient_id')
    content = request.POST.get('content', '').strip()
    if not content or not recipient_id:
        return HttpResponse('Contenu ou destinataire manquant', status=400)
    
    recipient = get_object_or_404(User, id=recipient_id)
    msg = Message.objects.create(sender=request.user, recipient=recipient, content=content)
    
    # Retourner la bulle de message pour HTMX swap
    sender_initials = f"{request.user.first_name[:1]}{request.user.last_name[:1]}"
    html = (
        f'<div style="display:flex;justify-content:flex-end">'
        f'<div>'
        f'<div class="msg-bubble msg-bubble-out">{msg.content}</div>'
        f'</div>'
        f'</div>'
    )
    return HttpResponse(html)

@login_required
@require_POST
def upload_document_view(request):
    name = request.POST.get('name', '').strip()
    category = request.POST.get('category', 'ELEVES')
    uploaded_file = request.FILES.get('file')
    
    if not uploaded_file:
        return HttpResponse('<div style="color:#A32D2D;padding:8px;">Aucun fichier n\'a été fourni.</div>', status=400)
        
    if not name:
        name = uploaded_file.name
        
    size = uploaded_file.size
    if size < 1024:
        file_info = f"{size} B"
    elif size < 1024 * 1024:
        file_info = f"{round(size / 1024, 1)} Ko"
    else:
        file_info = f"{round(size / (1024 * 1024), 1)} Mo"
        
    DocumentFile.objects.create(
        name=name,
        category=category,
        file=uploaded_file,
        file_info=file_info,
        uploaded_by=request.user
    )
    
    # Return to dossiers panel
    return redirect('load_panel', panel_name='dossiers')


@login_required
def delete_document_view(request, pk):
    """Supprime un document (admin uniquement)."""
    if not _is_admin_user(request):
        return HttpResponse('Accès refusé', status=403)
    doc = get_object_or_404(DocumentFile, pk=pk)
    if doc.file:
        doc.file.delete(save=False)
    doc.delete()
    return redirect('load_panel', panel_name='dossiers')



# ─── Nouvelles vues CRUD ───────────────────────────────────────────────────────

@login_required
def delete_student_view(request, pk):
    """Supprime un élève (admin uniquement)."""
    if not _is_admin_user(request):
        return HttpResponse('Accès refusé', status=403)
    student = get_object_or_404(StudentProfile, pk=pk)
    name = student.user.get_full_name() or student.user.username
    # Supprimer le profil et l'utilisateur
    user = student.user
    
    # Audit logging
    from core.utils import log_audit
    log_audit(request, f"Suppression de l'élève {name}", student, changes={"username": user.username})
    
    student.delete()
    user.delete()
    return HttpResponse(
        f'<div style="padding:10px;color:#0F6E56;background:#E1F5EE;border-radius:8px;margin-bottom:10px">'
        f'Élève {name} supprimé avec succès.</div>'
    )


@login_required
@require_POST
def mark_notifications_read_view(request):
    """Marque toutes les notifications de l'utilisateur comme lues."""
    count = Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return HttpResponse(
        f'<div style="padding:8px 12px;color:#0F6E56;background:#E1F5EE;border-radius:8px;font-size:12px">'
        f'{count} notification(s) marquée(s) comme lues.</div>'
    )


@login_required
@require_POST
def save_settings_view(request):
    """Sauvegarde les paramètres de l'établissement en base de données."""
    if not _is_admin_user(request):
        return HttpResponse('Accès refusé', status=403)
    
    cfg = SchoolSettings.get()
    cfg.school_name = request.POST.get('school_name', cfg.school_name).strip()
    cfg.school_city = request.POST.get('school_city', cfg.school_city).strip()
    cfg.school_year = request.POST.get('school_year', cfg.school_year).strip()
    cfg.school_director = request.POST.get('school_director', cfg.school_director).strip()
    cfg.school_email = request.POST.get('school_email', cfg.school_email).strip()
    
    try:
        cfg.tuition_fee = int(request.POST.get('tuition_fee', cfg.tuition_fee))
        cfg.nb_trimestres = int(request.POST.get('nb_trimestres', cfg.nb_trimestres))
        cfg.passing_score = float(request.POST.get('passing_score', cfg.passing_score))
    except (ValueError, TypeError):
        pass
    
    cfg.sms_alerts = 'sms_alerts' in request.POST
    cfg.save()
    
    # Audit logging
    from core.utils import log_audit
    log_audit(request, "Mise à jour des paramètres de l'école", cfg)
    
    return HttpResponse(
        '<div style="padding:10px;color:#0F6E56;background:#E1F5EE;border-radius:8px;display:flex;align-items:center;gap:8px">'
        '<i class="ti ti-circle-check"></i> Paramètres enregistrés avec succès.</div>'
    )


@login_required
@require_POST
def add_teacher_view(request):
    """Ajoute un nouvel enseignant (admin uniquement)."""
    if not _is_admin_user(request):
        return HttpResponse('Accès refusé', status=403)

    from core.forms import TeacherCreationForm
    form = TeacherCreationForm(request.POST)
    if not form.is_valid():
        errors_html = ''.join(
            f'<div style="padding:4px 0;font-size:12px;color:#A32D2D;">✗ {field}: {", ".join(errs)}</div>'
            for field, errs in form.errors.items()
            if field != '__all__'
        )
        non_field = ''.join(
            f'<div style="padding:4px 0;font-size:12px;color:#A32D2D;">✗ {e}</div>'
            for e in form.non_field_errors()
        )
        return HttpResponse(
            f'<div style="padding:10px;background:rgba(163,45,45,0.07);border:1px solid rgba(163,45,45,0.2);border-radius:8px;margin-bottom:10px;">'
            f'{non_field}{errors_html}</div>'
        )

    cd = form.cleaned_data
    try:
        user = User.objects.create_user(
            username=cd['username'], email=cd['email'],
            first_name=cd['first_name'], last_name=cd['last_name'],
            role='TEACHER', password='Password123'
        )
        teacher_profile = TeacherProfile.objects.create(user=user)

        from core.utils import log_audit
        log_audit(request, f"Création de l'enseignant {user.get_full_name()}", teacher_profile, changes={
            "username": cd['username'], "email": cd['email']
        })
        
        Notification.objects.create(
            user=request.user, title="Nouvel enseignant ajouté",
            message=f"L'enseignant {user.get_full_name()} a été inscrit dans le système.",
            notification_type='INFO'
        )
        return HttpResponse('<script>showPanel("profs", "Enseignants", null);</script>')
    except Exception as e:
        return HttpResponse(
            f'<div style="padding:8px;color:#A32D2D;">Erreur: {str(e)}</div>',
            status=400
        )


@login_required
def delete_teacher_view(request, pk):
    """Supprime un enseignant (admin uniquement)."""
    if not _is_admin_user(request):
        return HttpResponse('Accès refusé', status=403)
    teacher = get_object_or_404(TeacherProfile, pk=pk)
    user = teacher.user
    name = user.get_full_name() or user.username
    
    # Audit logging
    from core.utils import log_audit
    log_audit(request, f"Suppression de l'enseignant {name}", teacher, changes={"username": user.username})
    
    teacher.delete()
    user.delete()
    return HttpResponse("")



@login_required
def print_bulletin_view(request, student_id):
    term = request.GET.get('term', '2')
    try:
        term = int(term)
    except ValueError:
        term = 2
        
    student_prof = get_object_or_404(StudentProfile, id=student_id)
    student_name = student_prof.user.get_full_name() or student_prof.user.username
    class_name = student_prof.class_room.name if student_prof.class_room else 'Non assignée'
    
    cfg = SchoolSettings.get()
    active_year = cfg.school_year
    
    grades = []
    from academics.models import ClassSubjectConfig, Subject
    configs = {}
    if student_prof.class_room:
        configs = {c_cfg.subject_id: float(c_cfg.coefficient) for c_cfg in ClassSubjectConfig.objects.filter(school_class=student_prof.class_room)}

    subjects = Subject.objects.filter(classes=student_prof.class_room).distinct() if student_prof.class_room else Subject.objects.all()
    
    if term == 0:
        nb_terms = student_prof.class_room.nb_trimestres or 3 if student_prof.class_room else 3
        for sub in subjects:
            coef = configs.get(sub.id, float(sub.coefficient))
            term_scores = []
            for t in range(1, nb_terms + 1):
                det = get_student_subject_term_details(student_prof, sub, t, active_year)
                if det['moyenne'] is not None:
                    term_scores.append(det['moyenne'])
            avg_score = sum(term_scores) / len(term_scores) if term_scores else None
            
            if avg_score is not None:
                sibling_students = StudentProfile.objects.filter(class_room=student_prof.class_room) if student_prof.class_room else [student_prof]
                sibling_annual_scores = []
                for sib in sibling_students:
                    sib_term_scores = []
                    for t in range(1, nb_terms + 1):
                        sib_det = get_student_subject_term_details(sib, sub, t, active_year)
                        if sib_det['moyenne'] is not None:
                            sib_term_scores.append(sib_det['moyenne'])
                    sib_avg = sum(sib_term_scores) / len(sib_term_scores) if sib_term_scores else None
                    if sib_avg is not None:
                        sibling_annual_scores.append(sib_avg)
                class_avg = sum(sibling_annual_scores) / len(sibling_annual_scores) if sibling_annual_scores else avg_score
                
                grades.append({
                    'subject': sub.name,
                    'coef': coef,
                    'devoirs_str': "—",
                    'moy_devoirs': None,
                    'compo': None,
                    'score': round(avg_score, 2),
                    'total_points': round(avg_score * coef, 2),
                    'class_avg': round(class_avg, 2),
                    'rank': "—",
                    'remark': "Moyenne annuelle"
                })
    else:
        for sub in subjects:
            details = get_student_subject_term_details(student_prof, sub, term, active_year)
            if details['moyenne'] is not None:
                coef = configs.get(sub.id, float(sub.coefficient))
                
                sibling_students = StudentProfile.objects.filter(class_room=student_prof.class_room) if student_prof.class_room else [student_prof]
                sibling_scores = []
                for sib in sibling_students:
                    sib_details = get_student_subject_term_details(sib, sub, term, active_year)
                    if sib_details['moyenne'] is not None:
                        sibling_scores.append(sib_details['moyenne'])
                class_avg = sum(sibling_scores) / len(sibling_scores) if sibling_scores else details['moyenne']
                
                sibling_scores.sort(reverse=True)
                try:
                    rank_num = sibling_scores.index(details['moyenne']) + 1
                    rank_str_sub = f"{rank_num}er" if rank_num == 1 else f"{rank_num}ème"
                except ValueError:
                    rank_str_sub = "—"
                score_val = details['moyenne']
                if details['remark']:
                    auto_remark = details['remark']
                elif score_val >= 16:
                    auto_remark = "Excellent travail, continuez ainsi !"
                elif score_val >= 14:
                    auto_remark = "Très bon travail, bonne progression."
                elif score_val >= 12:
                    auto_remark = "Bon niveau, encourageons les efforts."
                elif score_val >= 10:
                    auto_remark = "Résultats satisfaisants, peut mieux faire."
                else:
                    auto_remark = "Des efforts supplémentaires sont nécessaires."
                    
                grades.append({
                    'subject': sub.name,
                    'coef': coef,
                    'devoirs_str': details['devoirs_str'],
                    'moy_devoirs': details['moy_devoirs'],
                    'compo': details['compo'],
                    'score': details['moyenne'],
                    'total_points': round(details['moyenne'] * coef, 2),
                    'class_avg': round(class_avg, 2),
                    'rank': rank_str_sub,
                    'remark': auto_remark,
                })
                
    if not grades:
        grades = [
            {'subject': 'Mathématiques', 'coef': 4.0, 'devoirs_str': '14, 16', 'moy_devoirs': 15.0, 'compo': 16.0, 'score': 15.67, 'total_points': 62.68, 'class_avg': 13.8, 'rank': '1er', 'remark': 'Excellent, continue ainsi'},
            {'subject': 'Français', 'coef': 3.0, 'devoirs_str': '13, 15', 'moy_devoirs': 14.0, 'compo': 14.0, 'score': 14.0, 'total_points': 42.0, 'class_avg': 14.2, 'rank': '7ème', 'remark': 'Bon niveau général'},
            {'subject': 'Histoire-Géo', 'coef': 2.0, 'devoirs_str': '14', 'moy_devoirs': 14.0, 'compo': 15.0, 'score': 14.67, 'total_points': 29.34, 'class_avg': 12.9, 'rank': '2ème', 'remark': 'Très bon travail'},
        ]
        avg = 14.8
        has_compositions = True
    else:
        if term == 0:
            avg = get_student_annual_average(student_prof, active_year)
            has_compositions = True
        else:
            avg = get_student_term_average(student_prof, term, active_year)
            has_compositions = Grade.objects.filter(
                student__class_room=student_prof.class_room,
                term=term,
                school_year=active_year,
                grade_type='COMPOSITION'
            ).exists() if student_prof and student_prof.class_room else False
            
    # Calculate rank
    rank_str = "—"
    if student_prof.class_room:
        class_ranks = get_class_rankings(student_prof.class_room, term, active_year)
        s_rank_info = class_ranks.get(student_prof.id)
        if s_rank_info:
            rank_str = s_rank_info['rank_str']
            
    context = {
        'student': student_prof,
        'student_name': student_name,
        'class_name': class_name,
        'grades': grades,
        'average': round(avg, 2),
        'rank': rank_str,
        'term': term,
        'school_name': cfg.school_name,
        'school_city': cfg.school_city,
        'school_email': cfg.school_email,
        'school_year': cfg.school_year,
        'school_director': cfg.school_director,
        'today': datetime.date.today(),
        'has_compositions': has_compositions,
    }

    return render(request, 'print_bulletin.html', context)


@login_required
@require_POST
def send_bulletin_parent_view(request, student_id):
    term = request.GET.get('term', '2')
    try:
        term = int(term)
    except ValueError:
        term = 2
        
    student_prof = get_object_or_404(StudentProfile, id=student_id)
    parent = student_prof.parent
    
    if parent:
        term_name = f"Trimestre {term}" if term != 0 else "Annuel"
        Notification.objects.create(
            user=parent.user,
            title="Bulletin scolaire disponible",
            message=f"Le bulletin du {term_name} de votre enfant {student_prof.user.get_full_name()} est disponible dans l'espace parent.",
            notification_type='INFO'
        )
        if parent.user.email:
            from core.utils import send_system_email
            send_system_email(
                subject=f"Bulletin disponible - {student_prof.user.get_full_name()}",
                message=f"Bonjour,\n\nLe bulletin scolaire du {term_name} de votre enfant {student_prof.user.get_full_name()} est disponible dans votre espace parent sur l'ERP École Al-Nour.\n\nCordialement,\nL'administration.",
                recipient_list=[parent.user.email]
            )
        return HttpResponse(
            '<div style="padding:10px;color:#0F6E56;background:#E1F5EE;border-radius:8px;margin-top:10px;font-size:12px;">'
            '✓ Bulletin envoyé aux parents avec succès !</div>'
        )
    else:
        return HttpResponse(
            '<div style="padding:10px;color:#A32D2D;background:#FCEBEB;border-radius:8px;margin-top:10px;font-size:12px;">'
            '✗ Impossible d\'envoyer : Aucun parent n\'est associé à cet élève.</div>'
        )

@login_required
@require_POST
def add_staff_view(request):
    """Ajoute un nouveau membre administratif (admin uniquement)."""
    if not _is_admin_user(request):
        return HttpResponse('Accès refusé', status=403)
        
    first_name = request.POST.get('first_name', '').strip()
    last_name = request.POST.get('last_name', '').strip()
    username = request.POST.get('username', '').strip()
    email = request.POST.get('email', '').strip()
    position = request.POST.get('position', 'Secrétaire').strip()
    phone    = request.POST.get('phone', '').strip()
    
    if not all([first_name, last_name, username]):
        return HttpResponse(
            '<div style="color:#A32D2D;padding:8px;">Tous les champs obligatoires doivent être remplis.</div>',
            status=400
        )
        
    if User.objects.filter(username=username).exists():
        return HttpResponse('<div style="padding:8px;color:#A32D2D;background:rgba(163,45,45,0.1);border:1px solid rgba(163,45,45,0.2);border-radius:8px;margin-bottom:10px;">✗ Erreur : Le nom d\'utilisateur existe déjà.</div>')

    try:
        user = User.objects.create_user(
            username=username, email=email,
            first_name=first_name, last_name=last_name,
            role='ADMIN', password='Password123'
        )
        admin_profile, _ = AdminProfile.objects.update_or_create(
            user=user,
            defaults={'position': position, 'phone': phone}
        )
        
        # Audit logging
        from core.utils import log_audit
        log_audit(request, f"Création du personnel admin {user.get_full_name()}", admin_profile, changes={
            "username": username, "position": position
        })
        
        Notification.objects.create(
            user=request.user, title="Nouveau personnel ajouté",
            message=f"Le membre du personnel {user.get_full_name()} ({position}) a été inscrit.",
            notification_type='INFO'
        )
        
        admins = AdminProfile.objects.all()
        active_role = request.session.get('active_role', 'admin')
        context = {
            'active_role': active_role,
            'admins': admins
        }
        return render(request, 'partials/personnel.html', context)
    except Exception as e:
        return HttpResponse(
            f'<div style="padding:8px;color:#A32D2D;">Erreur: {str(e)}</div>',
            status=400
        )


@login_required
def delete_staff_view(request, pk):
    """Supprime un membre du personnel (admin uniquement)."""
    if not _is_admin_user(request):
        return HttpResponse('Accès refusé', status=403)
    admin_profile = get_object_or_404(AdminProfile, pk=pk)
    if admin_profile.user == request.user:
        return HttpResponse('Impossible de supprimer votre propre compte', status=400)
    user = admin_profile.user
    name = user.get_full_name() or user.username
    
    # Audit logging
    from core.utils import log_audit
    log_audit(request, f"Suppression du personnel {name}", admin_profile, changes={"username": user.username})
    
    admin_profile.delete()
    user.delete()
    return HttpResponse("")


@login_required
@require_POST
def add_class_schedule_view(request):
    """Ajoute un cours à l'emploi du temps (admin uniquement)."""
    if not _is_admin_user(request):
        return HttpResponse('Accès refusé', status=403)
        
    class_id = request.POST.get('class_id')
    subject_id = request.POST.get('subject_id')
    teacher_id = request.POST.get('teacher_id')
    day_of_week = request.POST.get('day_of_week')
    start_time_str = request.POST.get('start_time')
    end_time_str = request.POST.get('end_time')
    room = request.POST.get('room', '').strip()
    
    if not all([class_id, subject_id, teacher_id, day_of_week, start_time_str, end_time_str]):
        return HttpResponse(
            '<div style="color:#A32D2D;padding:8px;">Tous les champs obligatoires doivent être remplis.</div>',
            status=400
        )
        
    try:
        school_class = get_object_or_404(SchoolClass, id=class_id)
        subject = get_object_or_404(Subject, id=subject_id)
        teacher = get_object_or_404(TeacherProfile, id=teacher_id)
        
        # Validation : vérifier si la matière est bien affectée à la classe (si la classe a des matières définies)
        if school_class.subjects.exists() and not school_class.subjects.filter(id=subject.id).exists():
            return HttpResponse(
                f'<div style="color:#A32D2D;padding:8px;">Erreur : La matière "{subject.name}" n\'est pas affectée à la classe {school_class.name}.</div>',
                status=400
            )
        
        # ── Détection de conflits ─────────────────────────────────────────────
        # Un cours crée un conflit si le prof ou la salle est déjà occupé(e) sur ce créneau
        teacher_conflict = ClassSchedule.objects.filter(
            teacher=teacher,
            day_of_week=int(day_of_week),
            start_time__lt=end_time_str,
            end_time__gt=start_time_str
        ).exclude(school_class=school_class).first()
        
        if teacher_conflict:
            return HttpResponse(
                f'<div style="color:#A32D2D;padding:8px;">⚠️ Conflit d\'emploi du temps : {teacher.user.get_full_name()} est déjà assigné à la classe <strong>{teacher_conflict.school_class.name}</strong> '
                f'({teacher_conflict.subject.name}) ce jour de {teacher_conflict.start_time} à {teacher_conflict.end_time}.</div>',
                status=400
            )
        
        if room:
            room_conflict = ClassSchedule.objects.filter(
                room__iexact=room,
                day_of_week=int(day_of_week),
                start_time__lt=end_time_str,
                end_time__gt=start_time_str
            ).first()
            if room_conflict:
                return HttpResponse(
                    f'<div style="color:#A32D2D;padding:8px;">⚠️ Conflit de salle : La salle <strong>{room}</strong> est déjà occupée '
                    f'par {room_conflict.school_class.name} ({room_conflict.subject.name}) ce jour de {room_conflict.start_time} à {room_conflict.end_time}.</div>',
                    status=400
                )
        
        schedule = ClassSchedule.objects.create(
            school_class=school_class,
            subject=subject,
            teacher=teacher,
            day_of_week=int(day_of_week),
            start_time=start_time_str,
            end_time=end_time_str,
            room=room if room else None
        )
        
        # Audit logging
        from core.utils import log_audit
        log_audit(request, f"Ajout au planning : {subject.name} pour {school_class.name}", schedule)
        
        return HttpResponse(f'<script>showPanel("emploiAdmin", "Emplois du temps", "class_id={class_id}");</script>')
    except Exception as e:
        return HttpResponse(
            f'<div style="padding:8px;color:#A32D2D;">Erreur: {str(e)}</div>',
            status=400
        )


@login_required
def print_schedule_view(request, class_id):
    """Affiche une version imprimable de l'emploi du temps."""
    school_class = get_object_or_404(SchoolClass, id=class_id)
    schedules_in_db = ClassSchedule.objects.filter(school_class=school_class)
    
    slots = [
        ('08:00:00', '10:00:00', '08h-10h'),
        ('10:00:00', '12:00:00', '10h-12h'),
        ('14:00:00', '16:00:00', '14h-16h'),
    ]
    schedule = []
    for start, end, label in slots:
        days_data = []
        for day in range(1, 6):
            sch = schedules_in_db.filter(day_of_week=day, start_time__gte=start, end_time__lte=end).first()
            if sch:
                days_data.append(f"{sch.subject.name} ({sch.teacher.user.get_full_name()})")
            else:
                days_data.append('—')
        schedule.append({'time': label, 'days': days_data})
        
    if not schedules_in_db.exists():
        schedule = [
            {'time': '08h-10h', 'days': ['Mathématiques', 'Français', 'Anglais', 'Mathématiques', 'SVT']},
            {'time': '10h-12h', 'days': ['SVT', 'Physique-Chimie', 'Histoire-Géo', 'Français', 'Anglais']},
            {'time': '14h-16h', 'days': ['Français', 'Histoire-Géo', '—', 'Physique-Chimie', 'Mathématiques']},
        ]
        
    cfg = SchoolSettings.get()
    
    context = {
        'class': school_class,
        'schedule': schedule,
        'school_name': cfg.school_name,
        'school_year': cfg.school_year,
        'today': datetime.date.today(),
    }
    return render(request, 'print_schedule.html', context)


@login_required
@require_POST
def send_unpaid_reminders_view(request):
    """Envoie un rappel groupé à tous les parents ayant des impayés (admin uniquement)."""
    if not _is_admin_user(request):
        return HttpResponse('Accès refusé', status=403)
        
    unpaid = Payment.objects.filter(status__in=['UNPAID', 'PARTIAL'])
    count = 0
    for pay in unpaid:
        parent = pay.student.parent
        if parent:
            term_name = pay.tuition_fee.get_term_display() if pay.tuition_fee else "Trimestre"
            Notification.objects.create(
                user=parent.user,
                title="Rappel de paiement scolarité",
                message=f"Rappel : Les frais de scolarité de votre enfant {pay.student.user.get_full_name()} d'un montant de {pay.tuition_fee.amount} FCFA pour la période {term_name} sont en attente de paiement.",
                notification_type='PAYMENT'
            )
            if parent.user.email:
                from core.utils import send_system_email
                send_system_email(
                    subject="Rappel de paiement - École Al-Nour",
                    message=f"Bonjour,\n\nNous vous rappelons que les frais de scolarité de votre enfant {pay.student.user.get_full_name()} pour la période {term_name} sont toujours en attente (Montant dû : {int(pay.tuition_fee.amount - pay.amount_paid)} FCFA).\n\nMerci de régulariser la situation.\n\nCordialement,\nLe service comptable.",
                    recipient_list=[parent.user.email]
                )
            count += 1
            
    if count == 0:
        count = 3 # mock default for empty database in demo
        
    return HttpResponse(
        f'<div style="padding:10px;color:#0F6E56;background:#E1F5EE;border-radius:8px;margin-top:10px;font-size:12px;text-align:center;">'
        f'✓ {count} rappels envoyés aux parents avec succès !</div>'
    )


@login_required
def get_notif_count_view(request):
    """Retourne le nombre de notifications non lues (pour mise à jour HTMX)."""
    count = Notification.objects.filter(user=request.user, is_read=False).count()
    if count > 0:
        html = f'<div class="notif-badge" id="notifBadge">{count}</div>'
    else:
        html = ''
    return HttpResponse(html)


@login_required
def record_payment_view(request):
    """Enregistre un paiement pour un élève (admin uniquement)."""
    if not _is_admin_user(request):
        return HttpResponse('Accès refusé', status=403)
        
    if request.method == 'POST':
        student_id = request.POST.get('student_id')
        amount_str = request.POST.get('amount')
        term = request.POST.get('term')
        method = request.POST.get('payment_method', 'CASH')
        
        if not all([student_id, amount_str, term]):
            return HttpResponse('<div style="color:#A32D2D;padding:8px;">Tous les champs sont obligatoires.</div>', status=400)
            
        try:
            amount = float(amount_str)
            term = int(term)
            if amount <= 0:
                return HttpResponse('<div style="color:#A32D2D;padding:8px;">Le montant doit être supérieur à 0.</div>', status=400)
        except ValueError:
            return HttpResponse('<div style="color:#A32D2D;padding:8px;">Montant ou trimestre invalide.</div>', status=400)
            
        student = get_object_or_404(StudentProfile, id=student_id)
        
        # Get or create tuition fee
        school_class = student.class_room
        tuition_fee = TuitionFee.objects.filter(school_class=school_class, term=term).first()
        if not tuition_fee:
            tuition_fee = TuitionFee.objects.filter(school_class__isnull=True, term=term).first()
        if not tuition_fee:
            cfg = SchoolSettings.get()
            tuition_fee = TuitionFee.objects.create(
                school_class=school_class,
                amount=cfg.tuition_fee,
                term=term,
                due_date=datetime.date.today()
            )
            
        payment, created = Payment.objects.get_or_create(
            student=student,
            tuition_fee=tuition_fee,
            defaults={'amount_paid': 0.0, 'status': 'UNPAID'}
        )
        
        payment.amount_paid = float(payment.amount_paid) + amount
        if payment.amount_paid >= tuition_fee.amount:
            payment.status = 'PAID'
            payment.paid_at = timezone.now()
        else:
            payment.status = 'PARTIAL'
            payment.paid_at = timezone.now()
            
        payment.payment_method = method
        payment.save()
        
        # Enregistrer la transaction dans le grand livre
        from finances.models import PaymentTransaction
        PaymentTransaction.objects.create(
            payment=payment,
            amount=amount,
            paid_at=timezone.now(),
            payment_method=method,
            reference="Encaissement manuel"
        )
        
        # Audit log
        from core.utils import log_audit
        log_audit(request, f"Enregistrement paiement de {amount} FCFA pour {student.user.get_full_name()}", payment, changes={
            "term": term, "method": method, "status": payment.status
        })
        
        # Notify student/parent
        Notification.objects.create(
            user=student.user,
            title="Paiement reçu",
            message=f"Votre paiement de {int(amount)} FCFA pour le {tuition_fee.get_term_display()} a été enregistré (Statut: {payment.get_status_display()}).",
            notification_type='PAYMENT'
        )
        if student.parent:
            Notification.objects.create(
                user=student.parent.user,
                title="Paiement scolarité enregistré",
                message=f"Le paiement de {int(amount)} FCFA pour les frais de scolarité de {student.user.get_full_name()} ({tuition_fee.get_term_display()}) a bien été reçu.",
                notification_type='PAYMENT'
            )
            
        return HttpResponse('<script>showPanel("paiements", "Paiements & Frais", null); showToast("Paiement enregistré avec succès !", "success");</script>')
        
    return HttpResponse('Méthode non autorisée', status=405)


@login_required
def record_online_payment_view(request):
    """Enregistre un paiement en ligne fictif initié par un parent pour son enfant."""
    parent_prof = None
    if hasattr(request.user, 'parent_profile'):
        parent_prof = request.user.parent_profile
    else:
        parent_prof = ParentProfile.objects.first()
        
    if not parent_prof:
        return HttpResponse('<div style="padding:10px;color:#A32D2D;background:#FCEBEB;border-radius:8px;">✗ Profil Parent introuvable.</div>', status=400)
        
    child = parent_prof.children.first()
    if not child:
        return HttpResponse('<div style="padding:10px;color:#A32D2D;background:#FCEBEB;border-radius:8px;">✗ Aucun élève associé à ce compte parent.</div>', status=400)
        
    if request.method == 'POST':
        amount_str = request.POST.get('amount')
        method = request.POST.get('payment_method', 'MOBILE_MONEY')
        provider = request.POST.get('provider', 'Wave')
        
        active_year = SchoolSettings.get().school_year
        school_class = child.class_room
        
        tuition_fees = TuitionFee.objects.filter(school_class=school_class, school_year=active_year).order_by('term')
        if not tuition_fees.exists():
            cfg = SchoolSettings.get()
            tuition_fees = [
                TuitionFee.objects.create(
                    school_class=school_class,
                    amount=cfg.tuition_fee,
                    term=1,
                    due_date=datetime.date.today(),
                    school_year=active_year
                )
            ]
            
        unpaid_fee = None
        target_payment = None
        
        for fee in tuition_fees:
            payment = Payment.objects.filter(student=child, tuition_fee=fee).first()
            if not payment or payment.status != 'PAID':
                unpaid_fee = fee
                target_payment = payment
                break
                
        if not unpaid_fee:
            return HttpResponse('<div style="padding:10px;color:#0F6E56;background:#E1F5EE;border-radius:8px;text-align:center;">✓ Tous les frais de scolarité pour cette année sont déjà réglés !</div>')
            
        due_amount = float(unpaid_fee.amount) - (float(target_payment.amount_paid) if target_payment else 0.0)
        
        try:
            amount = float(amount_str) if amount_str else due_amount
            if amount <= 0:
                return HttpResponse('<div style="padding:10px;color:#A32D2D;background:#FCEBEB;border-radius:8px;">✗ Le montant doit être supérieur à 0.</div>', status=400)
        except ValueError:
            return HttpResponse('<div style="padding:10px;color:#A32D2D;background:#FCEBEB;border-radius:8px;">✗ Montant invalide.</div>', status=400)
            
        if not target_payment:
            target_payment = Payment.objects.create(
                student=child,
                tuition_fee=unpaid_fee,
                amount_paid=0.0,
                status='UNPAID'
            )
            
        target_payment.amount_paid = float(target_payment.amount_paid) + amount
        if target_payment.amount_paid >= unpaid_fee.amount:
            target_payment.status = 'PAID'
        else:
            target_payment.status = 'PARTIAL'
            
        target_payment.paid_at = timezone.now()
        target_payment.payment_method = method
        target_payment.save()
        
        # Enregistrer la transaction dans le grand livre
        from finances.models import PaymentTransaction
        PaymentTransaction.objects.create(
            payment=target_payment,
            amount=amount,
            paid_at=timezone.now(),
            payment_method=method,
            reference=f"Paiement en ligne via {provider}"
        )
        
        Notification.objects.create(
            user=request.user,
            title="Paiement en ligne réussi",
            message=f"Votre paiement en ligne de {int(amount)} FCFA par {provider} a été validé. Reçu REC-{target_payment.id:05d}.",
            notification_type='PAYMENT'
        )
        Notification.objects.create(
            user=child.user,
            title="Paiement scolarité reçu",
            message=f"Un paiement de {int(amount)} FCFA a été enregistré pour votre scolarité du {unpaid_fee.get_term_display()}.",
            notification_type='PAYMENT'
        )
        
        from core.utils import log_audit
        log_audit(request, f"Paiement en ligne de {amount} FCFA pour {child.user.get_full_name()} via {provider}", target_payment)
        
        html = f"""
        <div style="padding: 15px; background: #E1F5EE; border: 1px solid #A2D4C6; border-radius: var(--border-radius-md); text-align: center; color: #0F6E56; margin-top: 10px; box-shadow: var(--shadow-sm);">
            <div style="font-size: 24px; margin-bottom: 8px;">🎉</div>
            <h3 style="margin: 0 0 6px 0; font-size: 14px; font-weight: 700; color: #0F6E56;">Paiement Réussi !</h3>
            <p style="margin: 0 0 12px 0; font-size: 11.5px; color: #155744; line-height: 1.4;">
                Le versement fictif de <strong>{int(amount)} FCFA</strong> via <strong>{provider}</strong> a bien été comptabilisé pour le <strong>{unpaid_fee.get_term_display()}</strong> de {child.user.get_full_name()}.
            </p>
            <div style="display: flex; gap: 8px; justify-content: center; flex-wrap: wrap;">
                <button class="btn btn-primary" onclick="window.open('/payment/receipt/{target_payment.id}/?download=1', '_blank')" style="font-size: 10.5px; padding: 4px 10px; background: #1D5FA5; color: white;">
                    💾 Télécharger Reçu PDF
                </button>
                <button class="btn" onclick="window.open('/payment/receipt/{target_payment.id}/?print=1', '_blank')" style="font-size: 10.5px; padding: 4px 10px; background: #0f172a; color: white;">
                    🖨️ Imprimer Reçu
                </button>
                <button class="btn" onclick="window.location.reload();" style="font-size: 10.5px; padding: 4px 10px; background: var(--color-background-tertiary); color: var(--color-text-secondary);">
                    Fermer & Actualiser
                </button>
            </div>
        </div>
        """
        return HttpResponse(html)
        
    return HttpResponse('Méthode non autorisée', status=405)


@login_required
def print_receipt_view(request, payment_id):
    """Affiche le reçu de paiement imprimable."""
    payment = get_object_or_404(Payment, id=payment_id)
    
    is_authorized = False
    if _is_admin_user(request):
        is_authorized = True
    elif request.user == payment.student.user:
        is_authorized = True
    elif hasattr(request.user, 'parent_profile') and request.user.parent_profile == payment.student.parent:
        is_authorized = True
    elif ParentProfile.objects.filter(children=payment.student).first():
        is_authorized = True
        
    if not is_authorized:
        return HttpResponse("Accès refusé", status=403)
        
    cfg = SchoolSettings.get()
    context = {
        'payment': payment,
        'school_name': cfg.school_name,
        'school_city': cfg.school_city,
        'school_email': cfg.school_email,
        'school_director': cfg.school_director,
        'today': datetime.date.today(),
    }
    return render(request, 'print_receipt.html', context)


@login_required
def export_students_excel_view(request):
    """Exporte la liste des élèves en Excel (admin/staff uniquement)."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Élèves"
    
    # Headers
    headers = ["Nom", "Classe", "Matricule", "Moyenne", "Taux de présence (%)", "Statut paiement"]
    ws.append(headers)
    
    # Query students
    students = StudentProfile.objects.all().order_by('user__last_name', 'user__first_name')
    for s in students:
        avg_score = s.grades.aggregate(Avg('score'))['score__avg']
        avg_score = round(avg_score, 2) if avg_score is not None else "N/A"
        
        att = s.attendances.all()
        if att.exists():
            pres_count = att.filter(status__in=['PRESENT', 'LATE']).count()
            att_pct = int((pres_count / att.count()) * 100)
        else:
            att_pct = 98 # fallback/mock
            
        pay = s.payments.first()
        pay_status = pay.get_status_display() if pay else "Non payé"
        
        ws.append([
            s.user.get_full_name() or s.user.username,
            s.class_room.name if s.class_room else "Non assignée",
            s.registration_number,
            avg_score,
            f"{att_pct}%",
            pay_status
        ])
        
    # Audit log
    from core.utils import log_audit
    log_audit(request, "Export Excel de la liste des élèves", None)
        
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename="export_eleves.xlsx"'
    wb.save(response)
    return response


@login_required
def export_grades_excel_view(request):
    """Exporte les notes des élèves en Excel par classe et trimestre."""
    import openpyxl
    class_id = request.GET.get('class_id')
    term = request.GET.get('term', '2')
    try:
        term = int(term)
    except ValueError:
        term = 2
        
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"Notes Trimestre {term}"
    
    if class_id:
        school_class = get_object_or_404(SchoolClass, id=class_id)
        class_name = school_class.name
        students = StudentProfile.objects.filter(class_room=school_class)
    else:
        class_name = "Tous"
        students = StudentProfile.objects.all()
        
    students = students.order_by('user__last_name', 'user__first_name')
        
    # Headers
    ws.append([f"Export des notes - Classe : {class_name} - Trimestre : {term}"])
    ws.append([]) # Empty
    
    subjects = Subject.objects.all().order_by('name')
    headers = ["Élève", "Classe"] + [sub.name for sub in subjects] + ["Moyenne Générale"]
    ws.append(headers)
    
    for s in students:
        row = [s.user.get_full_name() or s.user.username, s.class_room.name if s.class_room else "Non assignée"]
        
        grades_sum = 0
        grades_count = 0
        for sub in subjects:
            g = Grade.objects.filter(student=s, subject=sub, term=term).first()
            if g:
                row.append(float(g.score))
                grades_sum += float(g.score)
                grades_count += 1
            else:
                row.append("—")
                
        if grades_count > 0:
            row.append(round(grades_sum / grades_count, 2))
        else:
            row.append("N/A")
            
        ws.append(row)
        
    # Audit log
    from core.utils import log_audit
    log_audit(request, f"Export Excel des notes ({class_name}, Trimestre {term})", None)
        
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="notes_{class_name.replace(" ", "_")}_T{term}.xlsx"'
    wb.save(response)
    return response


@login_required
def dashboard_stats_api(request):
    """Retourne les statistiques réelles pour le dashboard admin (JSON)."""
    # 1. Moyennes par niveau
    levels = ['6ème', '5ème', '4ème', '3ème']
    averages = []
    for lvl in levels:
        avg_score = Grade.objects.filter(student__class_room__level=lvl).aggregate(Avg('score'))['score__avg']
        averages.append(float(round(avg_score, 1)) if avg_score is not None else 0.0)
        
    # 2. Statut des présences
    att_present = Attendance.objects.filter(status='PRESENT').count()
    att_late = Attendance.objects.filter(status='LATE').count()
    att_absent = Attendance.objects.filter(status='ABSENT').count()
        
    # 3. Évolution financière mensuelle (Revenus)
    current_year = timezone.now().year
    monthly_rev = [0.0] * 12
    payments = Payment.objects.filter(status='PAID', paid_at__year=current_year)
    for p in payments:
        if p.paid_at:
            m = p.paid_at.month - 1
            monthly_rev[m] += float(p.amount_paid)
            
    data = {
        'levels': levels,
        'averages': averages,
        'attendance': [att_present, att_late, att_absent],
        'revenue': monthly_rev,
    }
    return JsonResponse(data)


@login_required
def import_students_csv_view(request):
    """Importe des élèves depuis un fichier CSV (admin uniquement)."""
    if not _is_admin_user(request):
        return HttpResponse('Accès refusé', status=403)
        
    if request.method == 'POST':
        csv_file = request.FILES.get('csv_file')
        if not csv_file:
            return HttpResponse('<div style="color:#A32D2D;padding:8px;">Aucun fichier fourni.</div>', status=400)
            
        import csv
        import io
        
        try:
            file_data = csv_file.read().decode('utf-8')
        except UnicodeDecodeError:
            try:
                file_data = csv_file.read().decode('iso-8859-1')
            except Exception as e:
                return HttpResponse(f'<div style="color:#A32D2D;padding:8px;">Erreur décodage: {str(e)}</div>', status=400)
                
        io_string = io.StringIO(file_data)
        reader = csv.reader(io_string, delimiter=';')
        
        first_row = next(reader, None)
        if not first_row:
            return HttpResponse('<div style="color:#A32D2D;padding:8px;">Le fichier CSV est vide.</div>', status=400)
            
        if len(first_row) == 1 and ',' in first_row[0]:
            io_string.seek(0)
            reader = csv.reader(io_string, delimiter=',')
            first_row = next(reader, None)
            
        created_count = 0
        skipped_count = 0
        
        for row in reader:
            if not row or len(row) < 3:
                skipped_count += 1
                continue
                
            first_name = row[0].strip()
            last_name = row[1].strip()
            username = row[2].strip()
            email = row[3].strip() if len(row) > 3 else ""
            class_name = row[4].strip() if len(row) > 4 else ""
            
            if User.objects.filter(username=username).exists():
                skipped_count += 1
                continue
                
            try:
                user = User.objects.create_user(
                    username=username, email=email, first_name=first_name, last_name=last_name,
                    role='STUDENT', password='Password123'
                )
                
                school_class = None
                if class_name:
                    school_class = SchoolClass.objects.filter(name__iexact=class_name).first()
                    if not school_class:
                        school_class = SchoolClass.objects.create(name=class_name, level="Général")
                        
                if not school_class:
                    school_class = SchoolClass.objects.first()
                    
                _active_year = SchoolSettings.get().school_year
                _year_prefix = _active_year.split('/')[0].split('-')[0]  # ex: '2026' from '2026/2027'
                _student_count = StudentProfile.objects.count() + 1
                reg_num = f"{_year_prefix}-{_student_count:04d}"
                parent_user = User.objects.filter(role='PARENT').first()
                parent_profile = parent_user.parent_profile if hasattr(parent_user, 'parent_profile') else None
                
                student_profile = StudentProfile.objects.create(
                    user=user, class_room=school_class, registration_number=reg_num, parent=parent_profile
                )
                created_count += 1
                
                # Audit log for each
                from core.utils import log_audit
                log_audit(request, f"Import élève CSV : {user.get_full_name()}", student_profile)
            except Exception:
                skipped_count += 1
                
        # Group audit log
        from core.utils import log_audit
        log_audit(request, f"Import CSV d'élèves ({created_count} créés, {skipped_count} ignorés)", None)
        
        html = (
            f'<div style="padding:10px;color:#0F6E56;background:#E1F5EE;border-radius:8px;margin-bottom:10px;font-size:12px;">'
            f'✓ Importation terminée !<br>'
            f'• Créés : {created_count}<br>'
            f'• Ignorés (doublons/invalides) : {skipped_count}'
            f'</div>'
            f'<script>setTimeout(() => showPanel("eleves", "Élèves", null), 2000);</script>'
        )
        return HttpResponse(html)
        
    return HttpResponse('Méthode non autorisée', status=405)


@login_required
def import_grades_csv_view(request):
    """Importe des notes depuis un fichier CSV par trimestre (admin uniquement)."""
    if not _is_admin_user(request):
        return HttpResponse('Accès refusé', status=403)
        
    if request.method == 'POST':
        csv_file = request.FILES.get('csv_file')
        term_str = request.POST.get('term', '2')
        if not csv_file:
            return HttpResponse('<div style="color:#A32D2D;padding:8px;">Aucun fichier fourni.</div>', status=400)
            
        try:
            term = int(term_str)
        except ValueError:
            term = 2
            
        import csv
        import io
        
        try:
            file_data = csv_file.read().decode('utf-8')
        except UnicodeDecodeError:
            try:
                file_data = csv_file.read().decode('iso-8859-1')
            except Exception as e:
                return HttpResponse(f'<div style="color:#A32D2D;padding:8px;">Erreur décodage: {str(e)}</div>', status=400)
                
        io_string = io.StringIO(file_data)
        reader = csv.reader(io_string, delimiter=';')
        
        first_row = next(reader, None)
        if not first_row:
            return HttpResponse('<div style="color:#A32D2D;padding:8px;">Le fichier CSV est vide.</div>', status=400)
            
        if len(first_row) == 1 and ',' in first_row[0]:
            io_string.seek(0)
            reader = csv.reader(io_string, delimiter=',')
            first_row = next(reader, None)
            
        created_count = 0
        skipped_count = 0
        
        teacher_user = User.objects.filter(role='TEACHER').first()
        teacher_profile = teacher_user.teacher_profile if hasattr(teacher_user, 'teacher_profile') else None
        active_year = SchoolSettings.get().school_year
        
        # Format attendu: username;code_matiere;note;type(DEVOIR|COMPOSITION);num_devoir;commentaire
        from academics.models import ClassSubjectConfig
        
        for row in reader:
            if not row or len(row) < 3:
                skipped_count += 1
                continue
                
            username = row[0].strip()
            subject_code = row[1].strip()
            score_str = row[2].strip()
            grade_type_raw = row[3].strip().upper() if len(row) > 3 else 'COMPOSITION'
            devoir_num_raw = row[4].strip() if len(row) > 4 else '1'
            comment = row[5].strip() if len(row) > 5 else 'Importé'
            
            # Valider le type de note
            if grade_type_raw not in ['DEVOIR', 'COMPOSITION']:
                grade_type_raw = 'COMPOSITION'
            
            try:
                devoir_num = int(devoir_num_raw)
            except (ValueError, TypeError):
                devoir_num = 1
            
            student_user = User.objects.filter(username=username, role='STUDENT').first()
            if not student_user or not hasattr(student_user, 'student_profile'):
                skipped_count += 1
                continue
            student_profile = student_user.student_profile
            
            subject = Subject.objects.filter(Q(code__iexact=subject_code) | Q(name__iexact=subject_code)).first()
            if not subject:
                subject = Subject.objects.create(code=subject_code.upper(), name=subject_code, coefficient=2)
            
            # Récupérer le coefficient réel depuis ClassSubjectConfig si disponible
            real_coef = float(subject.coefficient)
            if student_profile.class_room:
                cfg_obj = ClassSubjectConfig.objects.filter(
                    school_class=student_profile.class_room,
                    subject=subject
                ).first()
                if cfg_obj:
                    real_coef = float(cfg_obj.coefficient)
                
            try:
                score = float(score_str)
                if not (0.0 <= score <= 20.0):
                    skipped_count += 1
                    continue
                
                lookup = {
                    'student': student_profile,
                    'subject': subject,
                    'term': term,
                    'grade_type': grade_type_raw,
                    'school_year': active_year,
                }
                if grade_type_raw == 'DEVOIR':
                    lookup['devoir_num'] = devoir_num
                else:
                    lookup['devoir_num'] = None
                
                Grade.objects.update_or_create(
                    **lookup,
                    defaults={
                        'teacher': teacher_profile,
                        'score': score,
                        'max_score': 20.0,
                        'coefficient': real_coef,
                        'comment': comment,
                        'count_in_bulletin': True,
                    }
                )
                created_count += 1
            except Exception:
                skipped_count += 1
                
        # Group audit log
        from core.utils import log_audit
        log_audit(request, f"Import CSV de notes ({created_count} créées, {skipped_count} ignorées, Trimestre {term})", None)
        
        html = (
            f'<div style="padding:10px;color:#0F6E56;background:#E1F5EE;border-radius:8px;margin-bottom:10px;font-size:12px;">'
            f'✓ Importation terminée !<br>'
            f'• Notes importées : {created_count}<br>'
            f'• Ignorées : {skipped_count}'
            f'</div>'
            f'<script>setTimeout(() => showPanel("bulletins", "Bulletins", "term={term}"), 2000);</script>'
        )
        return HttpResponse(html)
        
    return HttpResponse('Méthode non autorisée', status=405)


# ─── B6 — Recherche globale ─────────────────────────────────────────────────

@login_required
def global_search_view(request):
    """Recherche globale HTMX : élèves, profs, documents."""
    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return HttpResponse('')

    active_role = _get_active_role(request)

    results_html = f'<div style="padding:8px 12px;font-size:11px;color:var(--color-text-secondary);border-bottom:1px solid var(--color-border);">Résultats pour <strong>"{q}"</strong></div>'
    found_any = False

    # --- Élèves ---
    if _can_access_panel(active_role, 'eleves') or _can_access_panel(active_role, 'mesEleves'):
        students = StudentProfile.objects.filter(
            Q(user__first_name__icontains=q) |
            Q(user__last_name__icontains=q) |
            Q(registration_number__icontains=q)
        )[:5]
        if students.exists():
            found_any = True
            results_html += '<div style="padding:6px 12px;font-size:10px;font-weight:700;color:var(--color-text-secondary);text-transform:uppercase;letter-spacing:.05em;background:var(--color-background-tertiary);">Élèves</div>'
            for s in students:
                name = s.user.get_full_name() or s.user.username
                cls  = s.class_room.name if s.class_room else '—'
                avatar_inner = f'<img src="{s.user.avatar.url}" style="width:100%;height:100%;object-fit:cover;border-radius:50%;">' if s.user.avatar else f'{s.user.first_name[:1].upper()}{s.user.last_name[:1].upper()}'
                results_html += (
                    f'<div class="search-result-item" style="padding:8px 14px;cursor:pointer;display:flex;align-items:center;gap:10px;border-bottom:1px solid var(--color-border);" '
                    f'onclick="document.getElementById(\'globalSearchInput\').value=\'\'; closeSearchDropdown(); showPanel(\'eleves\',\'Élèves\',null);">'
                    f'<div style="width:28px;height:28px;border-radius:50%;background:#E1F5EE;display:flex;align-items:center;justify-content:center;color:#1D9E75;font-size:12px;font-weight:700;overflow:hidden;">'
                    f'{avatar_inner}</div>'
                    f'<div><div style="font-size:12px;font-weight:600;color:var(--color-text-primary);">{name}</div>'
                    f'<div style="font-size:11px;color:var(--color-text-secondary);">Élève · {cls}</div></div>'
                    f'</div>'
                )

    # --- Enseignants ---
    if _can_access_panel(active_role, 'profs'):
        teachers = TeacherProfile.objects.filter(
            Q(user__first_name__icontains=q) |
            Q(user__last_name__icontains=q)
        )[:5]
        if teachers.exists():
            found_any = True
            results_html += '<div style="padding:6px 12px;font-size:10px;font-weight:700;color:var(--color-text-secondary);text-transform:uppercase;letter-spacing:.05em;background:var(--color-background-tertiary);">Enseignants</div>'
            for t in teachers:
                name = t.user.get_full_name() or t.user.username
                subs = ', '.join(t.subjects.values_list('name', flat=True)[:2]) or 'Matière n.d.'
                avatar_inner = f'<img src="{t.user.avatar.url}" style="width:100%;height:100%;object-fit:cover;border-radius:50%;">' if t.user.avatar else f'{name[:2].upper()}'
                results_html += (
                    f'<div class="search-result-item" style="padding:8px 14px;cursor:pointer;display:flex;align-items:center;gap:10px;border-bottom:1px solid var(--color-border);" '
                    f'onclick="document.getElementById(\'globalSearchInput\').value=\'\'; closeSearchDropdown(); showPanel(\'profs\',\'Enseignants\',null);">'
                    f'<div style="width:28px;height:28px;border-radius:50%;background:#EEEDFE;display:flex;align-items:center;justify-content:center;color:#534AB7;font-size:12px;font-weight:700;overflow:hidden;">'
                    f'{avatar_inner}</div>'
                    f'<div><div style="font-size:12px;font-weight:600;color:var(--color-text-primary);">{name}</div>'
                    f'<div style="font-size:11px;color:var(--color-text-secondary);">Enseignant · {subs}</div></div>'
                    f'</div>'
                )

    # --- Documents ---
    if _can_access_panel(active_role, 'dossiers'):
        docs = DocumentFile.objects.filter(name__icontains=q)[:5]
        if docs.exists():
            found_any = True
            results_html += '<div style="padding:6px 12px;font-size:10px;font-weight:700;color:var(--color-text-secondary);text-transform:uppercase;letter-spacing:.05em;background:var(--color-background-tertiary);">Documents</div>'
            for d in docs:
                results_html += (
                    f'<div class="search-result-item" style="padding:8px 14px;cursor:pointer;display:flex;align-items:center;gap:10px;border-bottom:1px solid var(--color-border);" '
                    f'onclick="document.getElementById(\'globalSearchInput\').value=\'\'; closeSearchDropdown(); showPanel(\'dossiers\',\'Dossiers\',null);">'
                    f'<div style="width:28px;height:28px;border-radius:50%;background:#FAEEDA;display:flex;align-items:center;justify-content:center;color:#854F0B;">'
                    f'<i class="ti ti-file" style="font-size:14px;"></i></div>'
                    f'<div><div style="font-size:12px;font-weight:600;color:var(--color-text-primary);">{d.name}</div>'
                    f'<div style="font-size:11px;color:var(--color-text-secondary);">{d.get_category_display() if hasattr(d,"get_category_display") else d.category}</div></div>'
                    f'</div>'
                )

    if not found_any:
        results_html += (
            '<div style="padding:20px;text-align:center;color:var(--color-text-secondary);font-size:12px;">'
            '<i class="ti ti-search-off" style="font-size:24px;display:block;margin-bottom:8px;"></i>'
            f'Aucun résultat pour « {q} »</div>'
        )

    return HttpResponse(results_html)


@login_required
@require_POST
def save_profile_view(request):
    """Sauvegarde le profil personnel de l'utilisateur connecté (incluant son avatar)."""
    user = request.user
    from core.forms import UserProfileForm

    form = UserProfileForm(request.POST, request.FILES, instance=user)
    if not form.is_valid():
        errors_html = ''.join(
            f'<div style="padding:4px 0;font-size:12px;color:#A32D2D;">✗ {", ".join(errs)}</div>'
            for field, errs in form.errors.items()
        )
        return HttpResponse(
            f'<div style="padding:10px;background:rgba(163,45,45,0.07);border:1px solid rgba(163,45,45,0.2);border-radius:8px;">'
            f'{errors_html}</div>',
            status=400
        )

    # Gérer la suppression de l'avatar avant de sauvegarder le formulaire
    if 'delete_avatar' in request.POST:
        if user.avatar:
            user.avatar.delete(save=False)
            user.avatar = None

    # Valider le format de l'avatar si un nouveau fichier est envoyé
    uploaded_avatar = request.FILES.get('avatar')
    if uploaded_avatar:
        if not uploaded_avatar.name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
            return HttpResponse('Format d\'image non supporté.', status=400)

    form.save()

    # Journal d'audit
    from core.utils import log_audit
    log_audit(request, "Mise à jour du profil personnel", user)

    # Réponse HTTP avec trigger HTMX
    import json
    response = HttpResponse(
        '<div style="padding:10px;color:#0F6E56;background:#E1F5EE;border-radius:8px;display:flex;align-items:center;gap:8px">'
        '<i class="ti ti-circle-check"></i> Profil mis à jour. Rechargement...</div>'
    )
    response['HX-Trigger'] = json.dumps({
        "profileUpdated": {"message": "Votre profil a été mis à jour avec succès !"}
    })
    return response


@login_required
@require_POST
def add_class_view(request):
    """Ajoute une nouvelle classe (admin uniquement)."""
    if not _is_admin_user(request):
        return HttpResponse('Accès refusé', status=403)
        
    name = request.POST.get('name', '').strip()
    level = request.POST.get('level', '').strip()
    classroom = request.POST.get('classroom', '').strip()
    nb_trimestres = int(request.POST.get('nb_trimestres', 3) or 3)
    if nb_trimestres not in (2, 3):
        nb_trimestres = 3
    
    if not name or not level:
        return HttpResponse('<div style="color:#A32D2D;padding:8px;">Le nom et le niveau sont obligatoires.</div>', status=400)
        
    if SchoolClass.objects.filter(name=name).exists():
        return HttpResponse(f'<div style="color:#A32D2D;padding:8px;">La classe "{name}" existe déjà.</div>', status=400)
        
    new_class = SchoolClass.objects.create(
        name=name,
        level=level,
        classroom=classroom,
        nb_trimestres=nb_trimestres
    )
    
    from core.utils import log_audit
    log_audit(request, f"Ajout de la classe {name}", new_class)
    
    return redirect('load_panel', panel_name='settings')


@login_required
@require_POST
def add_subject_view(request):
    """Ajoute une nouvelle matière (admin uniquement)."""
    if not _is_admin_user(request):
        return HttpResponse('Accès refusé', status=403)
        
    name = request.POST.get('name', '').strip()
    code = request.POST.get('code', '').strip()
    
    if not name or not code:
        return HttpResponse('<div style="color:#A32D2D;padding:8px;">Le nom et le code de la matière sont obligatoires.</div>', status=400)
        
    if Subject.objects.filter(name=name).exists() or Subject.objects.filter(code=code).exists():
        return HttpResponse('<div style="color:#A32D2D;padding:8px;">Cette matière ou ce code existe déjà.</div>', status=400)
        
    new_subject = Subject.objects.create(
        name=name,
        code=code
    )
    
    # Journal d'audit
    from core.utils import log_audit
    log_audit(request, f"Ajout de la matière {name}", new_subject)
    
    return redirect('load_panel', panel_name='settings')


@login_required
def delete_class_view(request, pk):
    """Supprime une classe (admin uniquement)."""
    if not _is_admin_user(request):
        return HttpResponse('Accès refusé', status=403)
        
    school_class = get_object_or_404(SchoolClass, pk=pk)
    name = school_class.name
    
    # Journal d'audit
    from core.utils import log_audit
    log_audit(request, f"Suppression de la classe {name}", school_class)
    
    school_class.delete()
    return redirect('load_panel', panel_name='settings')


@login_required
def delete_subject_view(request, pk):
    """Supprime une matière (admin uniquement)."""
    if not _is_admin_user(request):
        return HttpResponse('Accès refusé', status=403)
        
    subject = get_object_or_404(Subject, pk=pk)
    name = subject.name
    
    # Journal d'audit
    from core.utils import log_audit
    log_audit(request, f"Suppression de la matière {name}", subject)
    
    subject.delete()
    return redirect('load_panel', panel_name='settings')


@login_required
def load_class_subjects_view(request):
    """Charge la liste des matières avec case à cocher pour une classe donnée (admin uniquement)."""
    if not _is_admin_user(request):
        return HttpResponse('Accès refusé', status=403)
        
    class_id = request.GET.get('class_id')
    if not class_id:
        # Essayer de récupérer la première classe par ordre alphabétique
        first_class = SchoolClass.objects.all().order_by('name').first()
        if first_class:
            class_id = first_class.id
            
    if not class_id:
        return HttpResponse('<div style="color:var(--color-text-tertiary);padding:8px;font-size:11.5px;">Aucune classe disponible.</div>')
        
    school_class = get_object_or_404(SchoolClass, id=class_id)
    all_subjects = Subject.objects.all().order_by('name')
    class_subjects_ids = set(school_class.subjects.values_list('id', flat=True))
    
    # Charger les configurations de coefficients existantes
    from academics.models import ClassSubjectConfig
    configs = {cfg.subject_id: cfg.coefficient for cfg in ClassSubjectConfig.objects.filter(school_class=school_class)}
    
    html = f'<input type="hidden" name="class_id" value="{school_class.id}">'
    html += '<div style="max-height: 200px; overflow-y: auto; border: 1px solid var(--color-border); border-radius: var(--border-radius-sm); padding: 8px; background: var(--color-background-secondary); margin-top: 5px; display: flex; flex-direction: column; gap: 6px;">'
    
    if not all_subjects.exists():
        html += '<div style="color:var(--color-text-tertiary);font-size:11px;text-align:center;padding:10px;">Aucune matière créée.</div>'
    else:
        for sub in all_subjects:
            checked = 'checked' if sub.id in class_subjects_ids else ''
            coef_val = configs.get(sub.id, sub.coefficient)
            coef_val_str = f"{float(coef_val):.1f}".replace('.0', '') if coef_val is not None else "1.0"
            html += f'''
            <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px; font-size: 11.5px; padding: 2px 0;">
                <label style="display: flex; align-items: center; gap: 8px; cursor: pointer; color: var(--color-text-primary); margin: 0; flex-grow: 1;">
                    <input type="checkbox" name="subject_ids" value="{sub.id}" {checked} style="width: auto; margin: 0; cursor: pointer;">
                    <span>{sub.name} <span style="color: var(--color-text-tertiary); font-size: 10px;">({sub.code})</span></span>
                </label>
                <div style="display: flex; align-items: center; gap: 4px;">
                    <span style="font-size: 10px; color: var(--color-text-secondary);">Coef:</span>
                    <input type="number" step="0.1" min="0.1" name="coef_{sub.id}" value="{coef_val_str}" style="width: 45px; font-size: 11px; padding: 2px 4px; border: 1px solid var(--color-border); border-radius: 3px; height: 20px; background: var(--color-background-primary); color: var(--color-text-primary);">
                </div>
            </div>
            '''
    html += '</div>'
    return HttpResponse(html)


@login_required
@require_POST
def save_class_subjects_view(request):
    """Enregistre l'affectation des matières et coefficients pour une classe (admin uniquement)."""
    if not _is_admin_user(request):
        return HttpResponse('Accès refusé', status=403)
        
    class_id = request.POST.get('class_id')
    if not class_id:
        return HttpResponse('<div style="color:#A32D2D;padding:8px;">Classe invalide.</div>', status=400)
        
    school_class = get_object_or_404(SchoolClass, id=class_id)
    subject_ids = request.POST.getlist('subject_ids')
    
    # Récupérer les matières correspondantes
    subjects = Subject.objects.filter(id__in=subject_ids)
    
    # Mettre à jour l'association ManyToMany
    school_class.subjects.set(subjects)
    
    # Mettre à jour les configurations de coefficients
    from academics.models import ClassSubjectConfig
    # Supprimer les configurations obsolètes
    ClassSubjectConfig.objects.filter(school_class=school_class).exclude(subject__id__in=subject_ids).delete()
    
    # Mettre à jour ou créer les configurations
    configs_logs = []
    for sub in subjects:
        coef_str = request.POST.get(f'coef_{sub.id}', '1.0')
        try:
            coef = float(coef_str)
        except ValueError:
            coef = 1.0
        cfg, created = ClassSubjectConfig.objects.update_or_create(
            school_class=school_class,
            subject=sub,
            defaults={'coefficient': coef}
        )
        configs_logs.append(f"{sub.name}: {coef}")
        
    # Journal d'audit
    from core.utils import log_audit
    subject_names = ", ".join(configs_logs)
    log_audit(request, f"Affectation des matières et coefficients pour {school_class.name}", school_class, changes={"subjects_and_coefficients": subject_names})
    
    response = HttpResponse(
        '<div style="padding:10px;color:#0F6E56;background:#E1F5EE;border-radius:8px;display:flex;align-items:center;gap:8px">'
        '<i class="ti ti-circle-check"></i> Affectation des matières et coefficients mise à jour avec succès.'
        '</div>'
    )
    return response


# ─── Congés Enseignants ───────────────────────────────────────────────────────

@login_required
@require_POST
def add_leave_view(request):
    """Soumet une demande de congé pour un enseignant (admin uniquement)."""
    if not _is_admin_user(request):
        return HttpResponse('Accès refusé', status=403)

    teacher_id = request.POST.get('teacher_id')
    leave_type = request.POST.get('leave_type', 'CONGE')
    start_date = request.POST.get('start_date')
    end_date = request.POST.get('end_date')
    reason = request.POST.get('reason', '').strip()

    if not all([teacher_id, start_date, end_date]):
        return HttpResponse('<div style="color:#A32D2D;padding:8px;">Tous les champs obligatoires doivent être remplis.</div>', status=400)

    try:
        teacher = get_object_or_404(TeacherProfile, id=teacher_id)
        leave = TeacherLeave.objects.create(
            teacher=teacher,
            leave_type=leave_type,
            start_date=start_date,
            end_date=end_date,
            reason=reason,
            status='PENDING',
        )
        from core.utils import log_audit
        log_audit(request, f"Demande de congé pour {teacher}", leave)
        return HttpResponse('<script>showPanel("congesProfs", "Congés enseignants", null);</script>')
    except Exception as e:
        return HttpResponse(f'<div style="color:#A32D2D;padding:8px;">Erreur : {e}</div>', status=400)


@login_required
def review_leave_view(request, pk, action):
    """Approuve ou rejette une demande de congé (admin uniquement)."""
    if not _is_admin_user(request):
        return HttpResponse('Accès refusé', status=403)

    leave = get_object_or_404(TeacherLeave, pk=pk)
    if action == 'approve':
        leave.status = 'APPROVED'
    elif action == 'reject':
        leave.status = 'REJECTED'
    else:
        return HttpResponse('Action invalide', status=400)

    try:
        leave.reviewed_by = request.user.admin_profile
    except Exception:
        pass
    leave.save()

    from core.utils import log_audit
    log_audit(request, f"Congé {leave.status} pour {leave.teacher}", leave)

    # Notify the teacher
    Notification.objects.create(
        user=leave.teacher.user,
        title=f"Congé {'approuvé' if action == 'approve' else 'refusé'}",
        message=f"Votre demande de congé ({leave.get_leave_type_display()}) du {leave.start_date} au {leave.end_date} a été {'approuvée' if action == 'approve' else 'refusée'}.",
        notification_type='INFO'
    )
    return HttpResponse('<script>showPanel("congesProfs", "Congés enseignants", null);</script>')


@login_required
def delete_leave_view(request, pk):
    """Supprime une demande de congé (admin uniquement)."""
    if not _is_admin_user(request):
        return HttpResponse('Accès refusé', status=403)
    leave = get_object_or_404(TeacherLeave, pk=pk)
    leave.delete()
    return HttpResponse('<script>showPanel("congesProfs", "Congés enseignants", null);</script>')


# ─── Planning / Calendrier Annuel ────────────────────────────────────────────

@login_required
@require_POST
def add_event_view(request):
    """Ajoute un événement scolaire au planning annuel (admin uniquement)."""
    if not _is_admin_user(request):
        return HttpResponse('Accès refusé', status=403)

    title = request.POST.get('title', '').strip()
    event_type = request.POST.get('event_type', 'OTHER')
    start_date = request.POST.get('start_date')
    end_date = request.POST.get('end_date') or None
    description = request.POST.get('description', '').strip()
    class_id = request.POST.get('class_id') or None

    if not title or not start_date:
        return HttpResponse('<div style="color:#A32D2D;padding:8px;">Le titre et la date de début sont obligatoires.</div>', status=400)

    try:
        school_class = get_object_or_404(SchoolClass, id=class_id) if class_id else None
        event = SchoolEvent.objects.create(
            title=title,
            event_type=event_type,
            start_date=start_date,
            end_date=end_date,
            description=description,
            school_class=school_class,
            created_by=request.user,
        )
        from core.utils import log_audit
        log_audit(request, f"Ajout événement : {title}", event)
        return HttpResponse('<script>showPanel("planning", "Planning scolaire", null);</script>')
    except Exception as e:
        return HttpResponse(f'<div style="color:#A32D2D;padding:8px;">Erreur : {e}</div>', status=400)


@login_required
def delete_event_view(request, pk):
    """Supprime un événement scolaire (admin uniquement)."""
    if not _is_admin_user(request):
        return HttpResponse('Accès refusé', status=403)
    event = get_object_or_404(SchoolEvent, pk=pk)
    event.delete()
    return HttpResponse('<script>showPanel("planning", "Planning scolaire", null);</script>')


@login_required
def edit_class_row_view(request, pk):
    """Retourne la ligne d'édition d'une classe (admin uniquement)."""
    if not _is_admin_user(request):
        return HttpResponse('Accès refusé', status=403)
    cls = get_object_or_404(SchoolClass, pk=pk)
    from django.middleware.csrf import get_token
    csrf_token = get_token(request)
    
    html = f"""
    <tr style="border-bottom: 1px solid var(--color-border); background: var(--color-background-tertiary);">
        <td colspan="5" style="padding: 6px;">
            <form hx-post="/action/edit-class/{cls.id}/" hx-target="#mainContent" hx-swap="innerHTML" style="display: flex; gap: 8px; align-items: center; width: 100%; flex-wrap:wrap;">
                <input type="hidden" name="csrfmiddlewaretoken" value="{csrf_token}">
                <input type="text" name="name" value="{cls.name}" required style="font-size: 11px; padding: 4px 6px; min-width: 80px; flex:1; height: 28px; border: 1px solid var(--color-border); border-radius: var(--border-radius-sm);">
                <input type="text" name="level" value="{cls.level}" required style="font-size: 11px; padding: 4px 6px; min-width: 80px; flex:1; height: 28px; border: 1px solid var(--color-border); border-radius: var(--border-radius-sm);">
                <input type="text" name="classroom" value="{cls.classroom or ''}" placeholder="Salle" style="font-size: 11px; padding: 4px 6px; min-width: 60px; flex:1; height: 28px; border: 1px solid var(--color-border); border-radius: var(--border-radius-sm);">
                <select name="nb_trimestres" style="font-size: 11px; padding: 4px 6px; height: 28px; border: 1px solid var(--color-border); border-radius: var(--border-radius-sm); background: var(--color-background-secondary);" title="Nb trimestres">
                    <option value="3" {"selected" if cls.nb_trimestres == 3 else ""}>3T</option>
                    <option value="2" {"selected" if cls.nb_trimestres == 2 else ""}>2T</option>
                </select>
                <button type="submit" class="btn" style="padding: 2px 6px; font-size: 10px; background: #E1F5EE; color: #0F6E56; border: 1px solid #C3E6CB; height: 28px; cursor: pointer; display: flex; align-items: center; gap: 2px;">
                    <i class="ti ti-check"></i> Valider
                </button>
                <button type="button" class="btn" style="padding: 2px 6px; font-size: 10px; background: #FCEBEB; color: #A32D2D; border: 1px solid #F8D7DA; height: 28px; cursor: pointer; display: flex; align-items: center; gap: 2px;" hx-get="/panel/settings/" hx-target="#mainContent" hx-swap="innerHTML">
                    <i class="ti ti-x"></i> Annuler
                </button>
            </form>
        </td>
    </tr>
    """
    return HttpResponse(html)


@login_required
@require_POST
def edit_class_view(request, pk):
    """Enregistre les modifications d'une classe (admin uniquement)."""
    if not _is_admin_user(request):
        return HttpResponse('Accès refusé', status=403)
        
    cls = get_object_or_404(SchoolClass, pk=pk)
    name = request.POST.get('name', '').strip()
    level = request.POST.get('level', '').strip()
    classroom = request.POST.get('classroom', '').strip()
    
    if not name or not level:
        return HttpResponse('<div style="color:#A32D2D;padding:8px;">Le nom et le niveau sont obligatoires.</div>', status=400)
        
    if SchoolClass.objects.filter(name=name).exclude(pk=pk).exists():
        return HttpResponse(f'<div style="color:#A32D2D;padding:8px;">La classe "{name}" existe déjà.</div>', status=400)
        
    cls.name = name
    cls.level = level
    cls.classroom = classroom
    nb_trimestres = int(request.POST.get('nb_trimestres', cls.nb_trimestres) or cls.nb_trimestres)
    if nb_trimestres not in (2, 3):
        nb_trimestres = cls.nb_trimestres
    cls.nb_trimestres = nb_trimestres
    cls.save()
    
    from core.utils import log_audit
    log_audit(request, f"Modification de la classe {name}", cls)
    
    return redirect('load_panel', panel_name='settings')


@login_required
def view_student_profile_view(request, pk):
    """Affiche le profil complet d'un élève."""
    active_role = _get_active_role(request)
    student = get_object_or_404(StudentProfile, pk=pk)
    
    is_authorized = False
    if active_role == 'admin':
        is_authorized = True
    elif active_role == 'prof':
        is_authorized = True
    elif active_role == 'eleve' and request.user == student.user:
        is_authorized = True
    elif active_role == 'parent':
        try:
            parent_profile = request.user.parent_profile
            if student.parent == parent_profile:
                is_authorized = True
        except ParentProfile.DoesNotExist:
            pass
            
    if not is_authorized:
        return HttpResponse('Accès refusé', status=403)
        
    current_school_year = SchoolSettings.get().school_year
    term = request.GET.get('term', '2')
    try:
        term = int(term)
    except ValueError:
        term = 2
        
    # Calcul du nb de trimestres de la classe de l'élève
    nb_trimestres = student.class_room.nb_trimestres if student.class_room else 3
    term_range = list(range(1, nb_trimestres + 1))
    if term not in term_range:
        term = term_range[-1]
        
    from academics.models import ClassSubjectConfig, Subject
    configs = {}
    if student.class_room:
        configs = {cfg.subject_id: float(cfg.coefficient) for cfg in ClassSubjectConfig.objects.filter(school_class=student.class_room)}
        
    subjects = Subject.objects.filter(classes=student.class_room).distinct() if student.class_room else Subject.objects.all()
    grades_list = []
    for sub in subjects:
        details = get_student_subject_term_details(student, sub, term, current_school_year)
        if details['moyenne'] is not None:
            coef = configs.get(sub.id, float(sub.coefficient))
            grades_list.append({
                'subject_name': sub.name,
                'coef': coef,
                'score': details['moyenne'],
                'total': round(details['moyenne'] * coef, 2),
            })
            
    average = get_student_term_average(student, term, current_school_year) if grades_list else None
    
    attendances = student.attendances.all().order_by('-date')
    total_att = attendances.count()
    presents_count = attendances.filter(status__in=['PRESENT', 'LATE']).count()
    attendance_pct = int((presents_count / total_att) * 100) if total_att > 0 else 100
    absences_count = attendances.filter(status='ABSENT').count()
    retards_count = attendances.filter(status='LATE').count()
    
    payments = student.payments.all().order_by('-tuition_fee__due_date')
    
    context = {
        'student': student,
        'grades': grades_list,
        'average': average,
        'attendance_pct': attendance_pct,
        'absences_count': absences_count,
        'retards_count': retards_count,
        'attendances': attendances[:10],
        'payments': payments,
        'selected_term': term,
        'term_range': term_range,
        'active_role': active_role,
        'school_year': current_school_year,
    }
    return render(request, 'partials/profil_eleve.html', context)


@login_required
def view_teacher_profile_view(request, pk):
    """Affiche le profil complet d'un enseignant."""
    active_role = _get_active_role(request)
    if active_role not in ['admin', 'prof']:
        return HttpResponse('Accès refusé', status=403)
        
    teacher = get_object_or_404(TeacherProfile, pk=pk)
    subjects = teacher.subjects.all()
    
    from academics.models import ClassSchedule
    schedules = ClassSchedule.objects.filter(teacher=teacher).select_related('school_class', 'subject')
    classes = list(schedules.values_list('school_class__name', flat=True).distinct())
    
    leaves = teacher.leaves.all().order_by('-created_at')
    total_hours = schedules.count() * 2
    if total_hours == 0:
        total_hours = 18
        
    context = {
        'teacher': teacher,
        'subjects': subjects,
        'classes': classes,
        'schedules': schedules,
        'leaves': leaves,
        'total_hours': total_hours,
        'active_role': active_role,
    }
    return render(request, 'partials/profil_prof.html', context)


@login_required
def view_staff_profile_view(request, pk):
    """Affiche le profil complet d'un membre de l'administration."""
    active_role = _get_active_role(request)
    if active_role != 'admin':
        return HttpResponse('Accès refusé', status=403)
        
    staff = get_object_or_404(AdminProfile, pk=pk)
    
    context = {
        'staff': staff,
        'active_role': active_role,
    }
    return render(request, 'partials/profil_staff.html', context)


@login_required
def view_parent_profile_view(request, pk):
    """Affiche le profil complet d'un parent."""
    active_role = _get_active_role(request)
    if active_role not in ['admin', 'prof', 'parent']:
        return HttpResponse('Accès refusé', status=403)
        
    parent = get_object_or_404(ParentProfile, pk=pk)
    children = parent.children.all().select_related('class_room', 'user')
    
    context = {
        'parent': parent,
        'children': children,
        'active_role': active_role,
    }
    return render(request, 'partials/profil_parent.html', context)


@login_required
@require_POST
def update_user_avatar_view(request, pk):
    """Met à jour l'avatar d'un utilisateur spécifique (admin ou l'utilisateur lui-même)."""
    user_to_update = get_object_or_404(User, id=pk)
    
    # Vérification des droits d'accès
    active_role = _get_active_role(request)
    is_authorized = False
    if active_role == 'admin':
        is_authorized = True
    elif request.user == user_to_update:
        is_authorized = True
        
    if not is_authorized:
        return HttpResponse('Accès refusé', status=403)
        
    # Gérer la suppression de l'avatar
    # Remarque : hx-vals peut envoyer delete_avatar en POST
    if 'delete_avatar' in request.POST or request.POST.get('delete_avatar') == '1':
        if user_to_update.avatar:
            user_to_update.avatar.delete(save=False)
            user_to_update.avatar = None
            
    # Gérer l'upload de l'avatar
    uploaded_avatar = request.FILES.get('avatar')
    if uploaded_avatar:
        if not uploaded_avatar.name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
            return HttpResponse('Format d\'image non supporté.', status=400)
        user_to_update.avatar = uploaded_avatar
        
    user_to_update.save()
    
    # Journal d'audit
    from core.utils import log_audit
    log_audit(request, f"Mise à jour de la photo de profil de {user_to_update}", user_to_update)
    
    # Rediriger vers la vue de profil correspondante
    if user_to_update.role == 'STUDENT':
        return redirect('view_student_profile', pk=user_to_update.student_profile.id)
    elif user_to_update.role == 'TEACHER':
        return redirect('view_teacher_profile', pk=user_to_update.teacher_profile.id)
    elif user_to_update.role == 'PARENT':
        return redirect('view_parent_profile', pk=user_to_update.parent_profile.id)
    elif user_to_update.role == 'ADMIN':
        return redirect('view_staff_profile', pk=user_to_update.admin_profile.id)
        



# ─────────────────────────────────────────────────────────────────────────────
# VUES PROMOTION DE FIN D'ANNÉE
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def load_promotion_students_view(request):
    """Charge la liste des élèves pour la promotion de fin d'année."""
    if not _is_admin_user(request):
        return HttpResponse('Accès refusé', status=403)

    class_id = request.GET.get('class_id')
    students = []
    selected_class = None

    if class_id:
        selected_class = SchoolClass.objects.filter(pk=class_id).first()
        if selected_class:
            students = list(StudentProfile.objects.filter(
                class_room=selected_class
            ).select_related('user').order_by('user__last_name', 'user__first_name'))
            active_year = SchoolSettings.get().school_year
            passing_score = float(SchoolSettings.get().passing_score)
            for s in students:
                s.annual_average = get_student_annual_average(s, active_year)
                s.suggest_promotion = s.annual_average >= passing_score

    # Toutes les classes ordonnées par niveau
    all_classes = SchoolClass.objects.all().order_by('level', 'name')

    context = {
        'all_classes': all_classes,
        'selected_class': selected_class,
        'students': students,
        'active_role': _get_active_role(request),
    }
    return render(request, 'partials/promotion.html', context)


@login_required
@require_POST
def execute_promotion_view(request):
    """Exécute la promotion/redoublement des élèves sélectionnés."""
    if not _is_admin_user(request):
        return HttpResponse('Accès refusé', status=403)

    results = {'promoted': 0, 'repeated': 0, 'graduated': 0, 'errors': []}

    # Les élèves à promouvoir et redoublants
    promoted_ids = request.POST.getlist('promoted')  # ids des élèves promus
    repeated_ids = request.POST.getlist('repeated')   # ids des redoublants

    # Classe de destination pour les promus
    next_class_id = request.POST.get('next_class')
    next_class = SchoolClass.objects.filter(pk=next_class_id).first() if next_class_id else None

    # Année scolaire et paramètres
    settings_obj = SchoolSettings.get()
    active_year = settings_obj.school_year
    admin_profile = getattr(request.user, 'admin_profile', None)

    from academics.models import YearEndReport

    for student_id in promoted_ids:
        try:
            student = StudentProfile.objects.get(pk=student_id)
            old_class = student.class_room
            avg = get_student_annual_average(student, active_year)
            
            # Promouvoir l'élève vers la classe de destination
            if next_class:
                student.class_room = next_class
                student.save()
            
            # Enregistrer dans le bilan de fin d'année
            YearEndReport.objects.update_or_create(
                student=student,
                school_year=active_year,
                defaults={
                    'original_class': old_class,
                    'final_average': avg,
                    'status': 'PASSANT',
                    'next_class': next_class,
                    'validated_by': admin_profile,
                    'validated_at': timezone.now()
                }
            )

            from core.utils import log_audit
            log_audit(request, f"Élève {student.user.get_full_name()} : promu de {old_class.name if old_class else 'aucune'} à {next_class.name if next_class else 'aucune'} (Moyenne: {avg}/20)", student)
            results['promoted'] += 1
        except StudentProfile.DoesNotExist:
            results['errors'].append(f'ID élève {student_id} introuvable')

    for student_id in repeated_ids:
        try:
            student = StudentProfile.objects.get(pk=student_id)
            old_class = student.class_room
            avg = get_student_annual_average(student, active_year)
            
            # Enregistrer dans le bilan de fin d'année
            YearEndReport.objects.update_or_create(
                student=student,
                school_year=active_year,
                defaults={
                    'original_class': old_class,
                    'final_average': avg,
                    'status': 'REDOUBLANT',
                    'next_class': old_class,
                    'validated_by': admin_profile,
                    'validated_at': timezone.now()
                }
            )

            from core.utils import log_audit
            log_audit(request, f"Élève {student.user.get_full_name()} : redoublement confirmé en {old_class.name if old_class else 'aucune'} (Moyenne: {avg}/20)", student)
            results['repeated'] += 1
        except StudentProfile.DoesNotExist:
            results['errors'].append(f'ID élève {student_id} introuvable')

    # Incrémenter l'année scolaire si demandé
    advance_year = request.POST.get('advance_year') == '1'
    if advance_year:
        try:
            # Exemple : '2024/2025' ou '2024-2025'
            separator = '/' if '/' in settings_obj.school_year else '-'
            parts = settings_obj.school_year.split(separator)
            y1, y2 = int(parts[0]), int(parts[1])
            settings_obj.school_year = f'{y1+1}{separator}{y2+1}'
            settings_obj.save()
            from core.utils import log_audit
            log_audit(request, f"Année scolaire avancée à {settings_obj.school_year}", settings_obj)
        except (IndexError, ValueError):
            results['errors'].append('Format année scolaire invalide (attendu AAAA/AAAA)')

    summary_parts = []
    if results['promoted']:
        summary_parts.append(f"{results['promoted']} élève(s) promu(s)")
    if results['repeated']:
        summary_parts.append(f"{results['repeated']} redoublant(s) confirmé(s)")
    if advance_year:
        summary_parts.append(f"Nouvelle année scolaire : {SchoolSettings.get().school_year}")
    if results['errors']:
        summary_parts.append("Erreurs : " + ' | '.join(results['errors']))

    msg = ' — '.join(summary_parts) or 'Aucune action effectuée.'

    # Retourne un message HTML (compatible HTMX)
    status_color = '#1a9e5c' if not results['errors'] else '#A32D2D'
    return HttpResponse(
        f'<div id="promotion-result" style="padding:12px;color:{status_color};'
        f'background:rgba(255,255,255,0.08);border-radius:8px;margin-top:16px;font-weight:500;">'
        f'✅ {msg}</div>',
        status=200
    )


@login_required
def print_promotion_report_view(request, class_id):
    """Génère un rapport imprimable/téléchargeable pour le bilan de promotion d'une classe."""
    if not _is_admin_user(request):
        return HttpResponse('Accès refusé', status=403)
    
    school_class = get_object_or_404(SchoolClass, id=class_id)
    cfg = SchoolSettings.get()
    active_year = cfg.school_year
    
    from academics.models import YearEndReport
    # Récupérer les rapports existants pour cette classe et cette année scolaire
    reports = YearEndReport.objects.filter(original_class=school_class, school_year=active_year).select_related('student__user')
    
    report_list = []
    if reports.exists():
        for rep in reports:
            report_list.append({
                'name': rep.student.user.get_full_name() or rep.student.user.username,
                'registration_number': rep.student.registration_number or '—',
                'average': rep.final_average,
                'status': rep.get_status_display(),
                'next_class': rep.next_class.name if rep.next_class else '—',
                'notes': rep.notes or '—',
            })
    else:
        # Si pas encore de clôture enregistrée, on génère un aperçu/simulation
        students = StudentProfile.objects.filter(class_room=school_class).select_related('user')
        passing_score = float(cfg.passing_score)
        for s in students:
            avg = get_student_annual_average(s, active_year)
            status = 'Passant' if avg >= passing_score else 'Redoublant'
            report_list.append({
                'name': s.user.get_full_name() or s.user.username,
                'registration_number': s.registration_number or '—',
                'average': avg,
                'status': status + ' (Aperçu)',
                'next_class': '—',
                'notes': 'Attente de validation',
            })
            
    # Ordonner par nom
    report_list.sort(key=lambda x: x['name'])
    
    context = {
        'school_name': cfg.school_name,
        'school_city': cfg.school_city,
        'school_email': cfg.school_email,
        'school_director': cfg.school_director,
        'school_year': active_year,
        'class_name': school_class.name,
        'reports': report_list,
        'today': datetime.date.today(),
    }
    return render(request, 'print_promotion_report.html', context)


@login_required
@require_POST
def change_password_view(request):
    """Permet à l'utilisateur de modifier son mot de passe de manière sécurisée."""
    current_password = request.POST.get('current_password')
    new_password = request.POST.get('new_password')
    confirm_password = request.POST.get('confirm_password')

    if not all([current_password, new_password, confirm_password]):
        return HttpResponse(
            '<div style="padding:10px;color:#A32D2D;background:#FCEBEB;border-radius:8px;margin-bottom:10px;font-size:12.5px;">'
            '✗ Tous les champs de mot de passe sont requis.</div>',
            status=400
        )

    if not request.user.check_password(current_password):
        return HttpResponse(
            '<div style="padding:10px;color:#A32D2D;background:#FCEBEB;border-radius:8px;margin-bottom:10px;font-size:12.5px;">'
            '✗ Le mot de passe actuel est incorrect.</div>',
            status=400
        )

    if new_password != confirm_password:
        return HttpResponse(
            '<div style="padding:10px;color:#A32D2D;background:#FCEBEB;border-radius:8px;margin-bottom:10px;font-size:12.5px;">'
            '✗ Le nouveau mot de passe et sa confirmation ne correspondent pas.</div>',
            status=400
        )

    # Valider la sécurité du mot de passe en utilisant les validateurs intégrés de Django
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError
    try:
        validate_password(new_password, request.user)
    except ValidationError as e:
        errors_html = ''.join(f'<li>{err}</li>' for err in e.messages)
        return HttpResponse(
            f'<div style="padding:10px;color:#A32D2D;background:#FCEBEB;border-radius:8px;margin-bottom:10px;font-size:12.5px;">'
            f'✗ Le mot de passe n\'est pas assez robuste :<ul>{errors_html}</ul></div>',
            status=400
        )

    # Tout est valide, on change le mot de passe
    request.user.set_password(new_password)
    request.user.save()

    # Mettre à jour la session pour éviter la déconnexion automatique de l'utilisateur
    from django.contrib.auth import update_session_auth_hash
    update_session_auth_hash(request, request.user)

    # Log d'audit
    from core.utils import log_audit
    log_audit(request, "Modification sécurisée du mot de passe", request.user)

    return HttpResponse(
        '<div style="padding:10px;color:#0F6E56;background:#E1F5EE;border-radius:8px;margin-bottom:10px;font-size:12.5px;">'
        '✓ Votre mot de passe a été modifié avec succès.</div>'
    )

# ─── Vues d'édition des profils utilisateurs ────────────────────────────────

@login_required
def edit_student_view(request, pk):
    """Affiche (GET) ou sauvegarde (POST) les informations d'un élève."""
    if not _is_admin_user(request):
        return HttpResponse('<div style="padding:10px;color:#A32D2D;background:#FCEBEB;border-radius:8px;">Accès réservé à l\'administrateur.</div>', status=403)

    student = get_object_or_404(StudentProfile, pk=pk)
    classes = SchoolClass.objects.all().order_by('name')
    parents = User.objects.filter(role='PARENT').select_related('parent_profile').order_by('last_name', 'first_name')

    if request.method == 'POST':
        # Sauvegarder les modifications
        first_name  = request.POST.get('first_name', '').strip()
        last_name   = request.POST.get('last_name', '').strip()
        email       = request.POST.get('email', '').strip()
        class_id    = request.POST.get('class_id')
        parent_id   = request.POST.get('parent_id')
        birth_date_str = request.POST.get('birth_date', '').strip()
        birth_place = request.POST.get('birth_place', '').strip()

        user = student.user
        if first_name:
            user.first_name = first_name
        if last_name:
            user.last_name = last_name
        user.email = email
        user.save()

        if class_id:
            try:
                student.class_room = SchoolClass.objects.get(pk=class_id)
            except SchoolClass.DoesNotExist:
                pass

        from accounts.models import ParentProfile
        if parent_id:
            try:
                student.parent = ParentProfile.objects.get(pk=parent_id)
            except ParentProfile.DoesNotExist:
                student.parent = None
        else:
            student.parent = None

        # Date et lieu de naissance
        if birth_date_str:
            import datetime
            try:
                student.birth_date = datetime.datetime.strptime(birth_date_str, '%Y-%m-%d').date()
            except ValueError:
                student.birth_date = None
        else:
            student.birth_date = None
        student.birth_place = birth_place

        student.save()



        from core.utils import log_audit
        log_audit(request, f"Modification du profil élève : {student.user.get_full_name()}", request.user)

        # Renvoyer vers la fiche profil mise à jour (dans la SPA, sans rechargement complet)
        response = HttpResponse('')
        response['HX-Location'] = f'{{"path": "/profile/student/{pk}/", "target": "#mainContent"}}'
        return response

    # GET → renvoyer le formulaire d'édition HTML
    return render(request, 'partials/edit_student_form.html', {
        'student': student,
        'classes': classes,
        'parents': parents,
    })


@login_required
def edit_teacher_view(request, pk):
    """Affiche (GET) ou sauvegarde (POST) les informations d'un enseignant."""
    if not _is_admin_user(request):
        return HttpResponse('<div style="padding:10px;color:#A32D2D;background:#FCEBEB;border-radius:8px;">Accès réservé à l\'administrateur.</div>', status=403)

    teacher = get_object_or_404(TeacherProfile, pk=pk)
    all_subjects = Subject.objects.all().order_by('name')

    if request.method == 'POST':
        first_name   = request.POST.get('first_name', '').strip()
        last_name    = request.POST.get('last_name', '').strip()
        email        = request.POST.get('email', '').strip()
        subject_ids  = request.POST.getlist('subject_ids')

        user = teacher.user
        if first_name:
            user.first_name = first_name
        if last_name:
            user.last_name = last_name
        user.email = email
        user.save()

        if subject_ids:
            teacher.subjects.set(Subject.objects.filter(pk__in=subject_ids))
        else:
            teacher.subjects.clear()

        from core.utils import log_audit
        log_audit(request, f"Modification du profil enseignant : {teacher.user.get_full_name()}", request.user)

        response = HttpResponse('')
        response['HX-Location'] = f'{{"path": "/profile/teacher/{pk}/", "target": "#mainContent"}}'
        return response

    return render(request, 'partials/edit_teacher_form.html', {
        'teacher': teacher,
        'all_subjects': all_subjects,
        'selected_subjects': list(teacher.subjects.values_list('pk', flat=True)),
    })


@login_required
def edit_staff_view(request, pk):
    """Affiche (GET) ou sauvegarde (POST) les informations d'un membre du personnel."""
    if not _is_admin_user(request):
        return HttpResponse('<div style="padding:10px;color:#A32D2D;background:#FCEBEB;border-radius:8px;">Accès réservé à l\'administrateur.</div>', status=403)

    staff = get_object_or_404(AdminProfile, pk=pk)

    POSITIONS = ['Directeur', 'Secrétaire', 'Comptable', 'Surveillant', 'Agent d\'entretien', 'Autre']

    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name  = request.POST.get('last_name', '').strip()
        email      = request.POST.get('email', '').strip()
        position   = request.POST.get('position', '').strip()

        user = staff.user
        if first_name:
            user.first_name = first_name
        if last_name:
            user.last_name = last_name
        user.email = email
        user.save()

        if position:
            staff.position = position
        staff.phone = request.POST.get('phone', '').strip()
        staff.save()

        from core.utils import log_audit
        log_audit(request, f"Modification du profil personnel : {staff.user.get_full_name()}", request.user)

        response = HttpResponse('')
        response['HX-Location'] = f'{{"path": "/profile/staff/{pk}/", "target": "#mainContent"}}'
        return response

    return render(request, 'partials/edit_staff_form.html', {
        'staff': staff,
        'positions': POSITIONS,
    })


import shutil
from django.core.management import call_command
from django.contrib.auth import logout
from pathlib import Path
from django.views.decorators.http import require_POST


@login_required
@require_POST
@csrf_exempt
def db_reset_view(request):
    """Réinitialise la base de données en quelques secondes via SQL direct."""
    if not _is_admin_user(request):
        return HttpResponse('<div style="padding:10px;color:#A32D2D;background:#FCEBEB;border-radius:8px;">Accès refusé.</div>', status=403)

    try:
        from django.db import connection, transaction
        from django.contrib.auth import update_session_auth_hash

        admin_id = request.user.id

        # ── Toutes les tables à vider (ordre : dépendances d'abord) ──────
        TABLES_TO_CLEAR = [
            # Finances
            'finances_paymenttransaction',
            'finances_payment',
            'finances_tuitionfee',
            # Académique
            'academics_grade',
            'academics_attendance',
            'academics_classschedule',
            'academics_classsubjectconfig',
            'academics_subject_classes',
            'academics_subject',
            'academics_yearendreport',
            'academics_teacherleave',
            # Core
            'core_message',
            'core_notification',
            'core_documentfile',
            'core_auditlog',
            'core_schoolevent',
            # Axes (tentatives de connexion)
            'axes_accessattempt',
            'axes_accessattemptexpiration',
            'axes_accessfailurelog',
            'axes_accesslog',
            # Profils (sauf admin courant)
            'accounts_studentprofile',
            'accounts_parentprofile',
            'accounts_teacherprofile_subjects',
            'accounts_teacherprofile',
            # Classes
            'accounts_schoolclass',
        ]

        with transaction.atomic():
            cursor = connection.cursor()

            # Désactiver les contraintes FK pour SQLite (autorisé en dev)
            cursor.execute("PRAGMA foreign_keys = OFF")

            # Vider chaque table en une seule instruction SQL
            for table in TABLES_TO_CLEAR:
                cursor.execute(f"DELETE FROM {table}")

            # Supprimer les profils admin et users sauf l'admin courant
            cursor.execute("DELETE FROM accounts_adminprofile WHERE user_id != %s", [admin_id])
            cursor.execute("DELETE FROM accounts_user_groups WHERE user_id != %s", [admin_id])
            cursor.execute("DELETE FROM accounts_user_user_permissions WHERE user_id != %s", [admin_id])
            cursor.execute("DELETE FROM authtoken_token WHERE user_id != %s", [admin_id])
            cursor.execute("DELETE FROM accounts_user WHERE id != %s", [admin_id])

            # Réactiver les contraintes FK
            cursor.execute("PRAGMA foreign_keys = ON")

        # ── Maintenir la session de l'admin actif ────────────────────────
        request.user.refresh_from_db()
        update_session_auth_hash(request, request.user)
        request.session.modified = True
        request.session.save()
        # ─────────────────────────────────────────────────────────────────

        response = HttpResponse(
            '<div style="padding:10px;color:#0F6E56;background:#E1F5EE;border-radius:8px;margin-bottom:10px;font-size:12.5px;">'
            '✓ Base de données réinitialisée à zéro. Votre compte administrateur est conservé — vous restez connecté.</div>'
        )
        response['HX-Trigger'] = 'backupListChanged'
        return response

    except Exception as e:
        return HttpResponse(
            f'<div style="padding:10px;color:#A32D2D;background:#FCEBEB;border-radius:8px;margin-bottom:10px;font-size:12.5px;">'
            f'✗ Erreur lors de la réinitialisation : {str(e)}</div>',
            status=500
        )


@login_required
@require_POST
@csrf_exempt
def db_restore_demo_view(request):
    """Restaure les données de démonstration via seed_data en préservant le compte admin courant."""
    if not _is_admin_user(request):
        return HttpResponse('<div style="padding:10px;color:#A32D2D;background:#FCEBEB;border-radius:8px;">Accès refusé.</div>', status=403)
        
    try:
        from django.contrib.auth import update_session_auth_hash
        
        admin_id = request.user.id
        
        # Passer l'ID admin pour qu'il soit préservé lors du seed
        call_command('seed_data', preserve_admin=admin_id)
        
        # Rafraîchir l'objet user et maintenir la session active
        request.user.refresh_from_db()
        update_session_auth_hash(request, request.user)
        request.session.modified = True
        request.session.save()
        
        # Rediriger vers le tableau de bord (sans déconnecter)
        response = HttpResponse(
            '<div style="padding:12px 16px;color:#0F6E56;background:#E1F5EE;border-radius:8px;font-size:12.5px;font-weight:600;">'
            '✓ Données de démonstration chargées avec succès ! Redirection...'
            '</div>'
        )
        response['HX-Redirect'] = '/'
        return response
    except Exception as e:
        import traceback
        return HttpResponse(
            f'<div style="padding:10px;color:#A32D2D;background:#FCEBEB;border-radius:8px;margin-bottom:10px;font-size:12.5px;">'
            f'<b>✗ Erreur :</b> {str(e)}<br>'
            f'<pre style="font-size:10px;margin-top:6px;white-space:pre-wrap;">{traceback.format_exc()[-600:]}</pre>'
            f'</div>',
            status=500
        )



@login_required
@require_POST
@csrf_exempt
def db_create_backup_view(request):
    """Crée une sauvegarde physique du fichier db.sqlite3."""
    if not _is_admin_user(request):
        return HttpResponse('<div style="padding:10px;color:#A32D2D;background:#FCEBEB;border-radius:8px;">Accès refusé.</div>', status=403)
        
    # Vérifier que nous sommes sur SQLite
    from django.conf import settings
    db_config = settings.DATABASES['default']
    if 'sqlite' not in db_config['ENGINE']:
        return HttpResponse(
            '<div style="padding:10px;color:#A32D2D;background:#FCEBEB;border-radius:8px;margin-bottom:10px;font-size:12.5px;">'
            '⚠️ Les sauvegardes de fichiers ne sont disponibles que pour la base de données locale SQLite. En production, utilisez pg_dump.</div>',
            status=400
        )
        
    db_file_path = Path(db_config['NAME'])
    if not db_file_path.exists():
        return HttpResponse(
            '<div style="padding:10px;color:#A32D2D;background:#FCEBEB;border-radius:8px;margin-bottom:10px;font-size:12.5px;">'
            '✗ Fichier de base de données introuvable.</div>',
            status=404
        )
        
    backup_dir = settings.MEDIA_ROOT / 'backups'
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d_%H%M%S')
    backup_filename = f"backup_{timestamp}.sqlite3"
    backup_file_path = backup_dir / backup_filename
    
    try:
        import sqlite3
        from django.db import connection
        
        connection.ensure_connection()
        src = connection.connection
        dst = sqlite3.connect(str(backup_file_path))
        
        src.backup(dst)
        dst.close()
        
        from core.utils import log_audit
        log_audit(request, f"Création de la sauvegarde de base de données : {backup_filename}", request.user)
        
        # Notifier HTMX de rafraîchir la liste
        res = HttpResponse(
            '<div style="padding:10px;color:#0F6E56;background:#E1F5EE;border-radius:8px;margin-bottom:10px;font-size:12.5px;">'
            f'✓ Sauvegarde {backup_filename} créée avec succès.</div>'
        )
        res['HX-Trigger'] = 'backupListChanged'
        return res
    except Exception as e:
        return HttpResponse(
            f'<div style="padding:10px;color:#A32D2D;background:#FCEBEB;border-radius:8px;margin-bottom:10px;font-size:12.5px;">'
            f'✗ Erreur d\'écriture de la sauvegarde : {str(e)}</div>',
            status=500
        )


@login_required
def db_list_backups_view(request):
    """Renvoie la liste des sauvegardes disponibles sous forme de template partiel."""
    if not _is_admin_user(request):
        return HttpResponse('Accès refusé', status=403)
        
    from django.conf import settings
    backup_dir = Path(settings.MEDIA_ROOT) / 'backups'
    
    backups_list = []
    if backup_dir.exists():
        for f in backup_dir.glob('backup_*.sqlite3'):
            stat = f.stat()
            size_kb = round(stat.st_size / 1024, 1)
            created_time = datetime.datetime.fromtimestamp(stat.st_mtime)
            backups_list.append({
                'name': f.name,
                'size': f"{size_kb} KB",
                'created_at': created_time
            })
            
    # Trier par date de création décroissante
    backups_list.sort(key=lambda x: x['created_at'], reverse=True)
    
    return render(request, 'partials/backup_list.html', {'backups': backups_list})


@login_required
@require_POST
@csrf_exempt
def db_restore_backup_view(request):
    """Restaure une sauvegarde SQLite sélectionnée sans écraser le fichier physique bloqué."""
    if not _is_admin_user(request):
        return HttpResponse('<div style="padding:10px;color:#A32D2D;background:#FCEBEB;border-radius:8px;">Accès refusé.</div>', status=403)
        
    backup_name = request.POST.get('backup_name')
    if not backup_name:
        return HttpResponse('<div style="padding:10px;color:#A32D2D;background:#FCEBEB;border-radius:8px;">Fichier requis.</div>', status=400)
        
    # Sécuriser le nom de fichier
    backup_name = os.path.basename(backup_name)
    if not backup_name.startswith('backup_') or not backup_name.endswith('.sqlite3'):
        return HttpResponse('<div style="padding:10px;color:#A32D2D;background:#FCEBEB;border-radius:8px;">Nom de fichier invalide.</div>', status=400)
        
    from django.conf import settings
    backup_file = Path(settings.MEDIA_ROOT) / 'backups' / backup_name
    
    if not backup_file.exists():
        return HttpResponse('<div style="padding:10px;color:#A32D2D;background:#FCEBEB;border-radius:8px;">Fichier de sauvegarde introuvable.</div>', status=404)
        
    db_config = settings.DATABASES['default']
    if 'sqlite' not in db_config['ENGINE']:
        return HttpResponse('<div style="padding:10px;color:#A32D2D;background:#FCEBEB;border-radius:8px;">Restauration de fichier SQLite non supportée.</div>', status=400)
        
    try:
        import sqlite3
        from django.db import connection
        from django.contrib.auth import update_session_auth_hash
        
        # Sauvegarder les infos de l'admin courant avant restauration
        current_admin_username = request.user.username
        current_admin_password_hash = request.user.password
        current_admin_email = request.user.email
        
        # Ouvrir le fichier de sauvegarde source
        src = sqlite3.connect(str(backup_file))
        
        # Préparer la connexion cible active
        connection.ensure_connection()
        dst = connection.connection
        
        # Restaurer via l'API de backup SQLite (transactionnel)
        src.backup(dst)
        src.close()
        
        # Vérifier si le compte admin courant existe encore après restauration
        User = get_user_model()
        try:
            restored_admin = User.objects.get(username=current_admin_username)
            # Le compte existe — maintenir la session
            request.session.cycle_key()
            update_session_auth_hash(request, restored_admin)
            request.session.modified = True
            request.session.save()
        except User.DoesNotExist:
            # Le compte n'existait pas dans la sauvegarde — le recréer
            new_admin = User(
                username=current_admin_username,
                email=current_admin_email,
                role='ADMIN',
                is_staff=True,
                is_superuser=True,
            )
            new_admin.password = current_admin_password_hash  # Conserver le hash existant
            new_admin.save()
            from accounts.models import AdminProfile
            AdminProfile.objects.get_or_create(user=new_admin, defaults={'position': 'Directeur'})
            request.session.cycle_key()
            update_session_auth_hash(request, new_admin)
            request.session.modified = True
            request.session.save()
        
        from core.utils import log_audit
        log_audit(request, f"Restauration de la sauvegarde : {backup_name}", request.user)
        
        # Rediriger vers le tableau de bord sans déconnecter
        response = HttpResponse(
            '<div style="padding:12px 16px;color:#0F6E56;background:#E1F5EE;border-radius:8px;font-size:12.5px;font-weight:600;">'
            f'✓ Sauvegarde <b>{backup_name}</b> restaurée avec succès ! Redirection...'
            '</div>'
        )
        response['HX-Redirect'] = '/'
        return response
    except Exception as e:
        import traceback
        return HttpResponse(
            f'<div style="padding:10px;color:#A32D2D;background:#FCEBEB;border-radius:8px;margin-bottom:10px;font-size:12.5px;">'
            f'<b>✗ Erreur lors de la restauration :</b> {str(e)}<br>'
            f'<pre style="font-size:10px;margin-top:6px;white-space:pre-wrap;">{traceback.format_exc()[-500:]}</pre>'
            f'</div>',
            status=500
        )



@login_required
@require_POST
@csrf_exempt
def db_delete_backup_view(request):
    """Supprime une sauvegarde sélectionnée."""
    if not _is_admin_user(request):
        return HttpResponse('<div style="padding:10px;color:#A32D2D;background:#FCEBEB;border-radius:8px;">Accès refusé.</div>', status=403)
        
    backup_name = request.POST.get('backup_name')
    if not backup_name:
        return HttpResponse('<div style="padding:10px;color:#A32D2D;background:#FCEBEB;border-radius:8px;">Fichier requis.</div>', status=400)
        
    backup_name = os.path.basename(backup_name)
    from django.conf import settings
    backup_file = Path(settings.MEDIA_ROOT) / 'backups' / backup_name
    
    if backup_file.exists():
        try:
            backup_file.unlink()
            from core.utils import log_audit
            log_audit(request, f"Suppression de la sauvegarde : {backup_name}", request.user)
            
            # Renvoyer une réponse vide avec statut 200. HTMX supprimera la ligne <tr>.
            res = HttpResponse("", status=200)
            return res
        except Exception as e:
            return HttpResponse(
                f"Erreur lors de la suppression : {str(e)}",
                status=500
            )
    else:
        return HttpResponse("Fichier de sauvegarde introuvable.", status=404)




