from rest_framework import serializers
from django.contrib.auth import get_user_model
from accounts.models import SchoolClass, StudentProfile, TeacherProfile
from academics.models import Subject, Grade, Attendance

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'email', 'role', 'avatar']
        read_only_fields = ['role']


class SchoolClassSerializer(serializers.ModelSerializer):
    class Meta:
        model = SchoolClass
        fields = ['id', 'name', 'level', 'classroom']


class StudentProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    class_room_details = SchoolClassSerializer(source='class_room', read_only=True)

    class Meta:
        model = StudentProfile
        fields = ['id', 'user', 'class_room', 'class_room_details', 'registration_number']


class SubjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subject
        fields = ['id', 'name', 'code']


class GradeSerializer(serializers.ModelSerializer):
    student_details = StudentProfileSerializer(source='student', read_only=True)
    
    class Meta:
        model = Grade
        fields = [
            'id', 'student', 'student_details', 'teacher', 'subject', 
            'term', 'score', 'max_score', 'coefficient', 'comment', 'created_at'
        ]


class AttendanceSerializer(serializers.ModelSerializer):
    student_details = StudentProfileSerializer(source='student', read_only=True)
    
    class Meta:
        model = Attendance
        fields = [
            'id', 'student', 'student_details', 'school_class', 
            'date', 'period', 'status', 'arrival_time', 'excuse'
        ]
