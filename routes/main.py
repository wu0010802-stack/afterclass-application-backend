
from flask import Blueprint, request, jsonify
from services.registration_service import RegistrationService
from services.admin_service import AdminService

main_bp = Blueprint('main', __name__)

@main_bp.route('/api/courses', methods=['GET'])
def get_courses_public():
    try:
        courses = AdminService.get_courses_stats()
        return jsonify(courses)
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@main_bp.route('/query-registration', methods=['GET'])
def query_registration():
    name = request.args.get('name')
    birthday = request.args.get('birthday')
    
    if not name:
        return jsonify({'message': 'Missing name parameter'}), 400
    
    try:
        result = RegistrationService.get_registration_by_student(name, birthday)
        if result:
            return jsonify(result)
        return jsonify({'message': 'Registration not found'}), 404
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@main_bp.route('/api/courses/availability', methods=['GET'])
def get_availability():
    try:
        availability = RegistrationService.get_course_availability()
        return jsonify(availability)
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@main_bp.route('/api/settings/registration-time', methods=['GET'])
def get_registration_time():
    try:
        settings = RegistrationService.get_registration_settings()
        return jsonify(settings)
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@main_bp.route('/api/course-videos', methods=['GET'])
def get_course_videos():
    try:
        videos = RegistrationService.get_course_videos()
        return jsonify(videos)
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@main_bp.route('/api/classes', methods=['GET'])
def get_classes():
    try:
        classes = RegistrationService.get_all_classes()
        return jsonify(classes)
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@main_bp.route('/submit-registration', methods=['POST'])
def submit_registration():
    try:
        data = request.get_json()
        result = RegistrationService.handle_registration(data, update=False)
        return jsonify(result), 200
    except ValueError as e:
        return jsonify({'message': str(e)}), 400
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@main_bp.route('/update-registration', methods=['POST'])
def update_registration():
    try:
        data = request.get_json()
        result = RegistrationService.handle_registration(data, update=True)
        return jsonify(result), 200
    except ValueError as e:
        return jsonify({'message': str(e)}), 400
    except Exception as e:
        return jsonify({'message': str(e)}), 500
