from django.contrib import admin
from .models import Subject, ClassSchedule, Grade, Attendance, YearEndReport

@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'code')
    search_fields = ('name', 'code')

@admin.register(ClassSchedule)
class ClassScheduleAdmin(admin.ModelAdmin):
    list_display = ('school_class', 'subject', 'teacher', 'day_of_week', 'start_time', 'end_time', 'room')
    list_filter = ('school_class', 'day_of_week', 'subject')
    search_fields = ('school_class__name', 'subject__name', 'teacher__user__first_name', 'teacher__user__last_name')

@admin.register(Grade)
class GradeAdmin(admin.ModelAdmin):
    list_display = ('student', 'subject', 'term', 'score', 'max_score', 'coefficient', 'count_in_bulletin', 'teacher')
    list_filter = ('term', 'subject', 'count_in_bulletin')
    search_fields = ('student__user__first_name', 'student__user__last_name', 'subject__name')

@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ('student', 'school_class', 'date', 'period', 'status', 'excuse', 'has_justification')
    list_filter = ('status', 'period', 'date', 'school_class')
    search_fields = ('student__user__first_name', 'student__user__last_name', 'school_class__name', 'excuse')
    readonly_fields = ('justification_file',)

    @admin.display(description='Justificatif', boolean=True)
    def has_justification(self, obj):
        return bool(obj.justification_file)

@admin.register(YearEndReport)
class YearEndReportAdmin(admin.ModelAdmin):
    list_display = ('student', 'school_year', 'original_class', 'final_average', 'status', 'next_class', 'validated_at')
    list_filter = ('school_year', 'status', 'original_class')
    search_fields = ('student__user__first_name', 'student__user__last_name', 'original_class__name', 'next_class__name')
