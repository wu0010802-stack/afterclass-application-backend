
from flask import Blueprint, request, jsonify, abort
from services.admin_service import AdminService
from config import Config
import secrets

import jwt
import datetime

admin_bp = Blueprint('admin', __name__)

def generate_token():
    payload = {
        'sub': 'admin',
        'iat': datetime.datetime.utcnow(),
        'exp': datetime.datetime.utcnow() + datetime.timedelta(days=7)
    }
    return jwt.encode(payload, Config.SECRET_KEY, algorithm='HS256')

def validate_token(token):
    try:
        jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
        return True
    except jwt.ExpiredSignatureError:
        return False
    except jwt.InvalidTokenError:
        return False

@admin_bp.before_request
def require_auth():
    # Bypass auth check for OPTIONS requests and the login endpoint.
    if request.method == 'OPTIONS' or request.endpoint == 'admin.login':
        return
        
    # For all other API endpoints in this blueprint, require authentication.
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return jsonify({'message': 'Authorization header missing or invalid'}), 401
    
    token = auth_header[7:]
    if not validate_token(token):
        return jsonify({'message': '無效或過期的 session，請重新登入'}), 401

@admin_bp.route('/admin/login', methods=['POST'])
def login():
    data = request.get_json()
    password = data.get('password', '')
    
    if password == Config.ADMIN_PASSWORD:
        token = generate_token()
        return jsonify({'message': '登入成功', 'token': token})
    else:
        return jsonify({'message': '密碼錯誤'}), 401

@admin_bp.route('/admin/stats', methods=['GET'])
def get_dashboard():
    try:
        data = AdminService.get_dashboard_stats()
        return jsonify(data)
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@admin_bp.route('/admin/registrations', methods=['GET'])
def get_registrations():
    try:
        data = AdminService.get_all_registrations()
        return jsonify(data)
    except Exception as e:
        print(f"Error getting registrations: {e}")
        return jsonify({'message': str(e)}), 500

@admin_bp.route('/admin/courses', methods=['GET'])
def get_courses():
    try:
        courses = AdminService.get_courses_stats()
        return jsonify({'courses': courses})
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@admin_bp.route('/admin/registration/<int:reg_id>', methods=['GET'])
def get_registration_detail(reg_id):
    try:
        data = AdminService.get_registration_detail(reg_id)
        if data:
            return jsonify(data)
        return jsonify({'message': 'Registration not found'}), 404
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@admin_bp.route('/admin/registration/<int:reg_id>', methods=['DELETE'])
def delete_registration(reg_id):
    try:
        AdminService.delete_registration(reg_id)
        return jsonify({'message': 'Deleted successfully'})
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@admin_bp.route('/admin/course', methods=['POST'])
def create_course():
    try:
        data = request.get_json()
        new_id = AdminService.create_course(data)
        return jsonify({'message': '課程新增成功', 'course_id': new_id})
    except ValueError as e:
        return jsonify({'message': str(e)}), 400
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@admin_bp.route('/admin/course/<int:course_id>', methods=['PUT'])
def update_course(course_id):
    try:
        data = request.get_json()
        AdminService.update_course(course_id, data)
        return jsonify({'message': 'Update successful'})
    except ValueError as e:
        return jsonify({'message': str(e)}), 400
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@admin_bp.route('/admin/course/<int:course_id>', methods=['DELETE'])
def delete_course(course_id):
    try:
        AdminService.delete_course(course_id)
        return jsonify({'message': '課程已刪除'})
    except ValueError as e:
        return jsonify({'message': str(e)}), 400
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@admin_bp.route('/admin/classes', methods=['GET'])
def get_classes():
    try:
        classes = AdminService.get_classes()
        return jsonify(classes)
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@admin_bp.route('/admin/class', methods=['POST'])
def create_class():
    try:
        data = request.get_json()
        name = data.get('name')
        if not name:
            return jsonify({'message': '班級名稱為必填'}), 400
            
        new_id = AdminService.create_class(name)
        return jsonify({'message': '班級新增成功', 'id': new_id})
    except ValueError as e:
        return jsonify({'message': str(e)}), 400
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@admin_bp.route('/admin/class/<int:class_id>', methods=['PUT'])
def update_class(class_id):
    try:
        data = request.get_json()
        name = data.get('name')
        if not name:
            return jsonify({'message': '班級名稱為必填'}), 400
            
        AdminService.update_class(class_id, name)
        return jsonify({'message': '班級更新成功'})
    except ValueError as e:
        return jsonify({'message': str(e)}), 400
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@admin_bp.route('/admin/class/<int:class_id>', methods=['DELETE'])
def delete_class(class_id):
    try:
        AdminService.delete_class(class_id)
        return jsonify({'message': '班級刪除成功'})
    except ValueError as e:
        return jsonify({'message': str(e)}), 400
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@admin_bp.route('/admin/waitlist/promote/<int:registration_course_id>', methods=['POST'])
def promote_waitlist(registration_course_id):
    try:
        result = AdminService.promote_from_waitlist(registration_course_id)
        return jsonify(result)
    except ValueError as e:
        return jsonify({'message': str(e)}), 400
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@admin_bp.route('/admin/waitlist/<int:registration_course_id>', methods=['DELETE'])
def delete_waitlist(registration_course_id):
    try:
        result = AdminService.delete_waitlist_entry(registration_course_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@admin_bp.route('/admin/settings/registration-time', methods=['POST'])
def update_settings():
    try:
        data = request.get_json()
        start = data.get('start')
        end = data.get('end')
        if not start or not end:
            return jsonify({'message': 'Missing start or end time'}), 400
            
        AdminService.update_settings(start, end)
        return jsonify({'message': 'Registration time updated successfully'})
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@admin_bp.route('/admin/registration/<int:reg_id>/payment', methods=['PUT'])
def toggle_payment(reg_id):
    try:
        data = request.get_json()
        paid = data.get('paid', False)
        AdminService.toggle_payment(reg_id, paid)
        status = '已繳費' if paid else '未繳費'
        return jsonify({'message': f'更新成功，狀態為：{status}'})
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@admin_bp.route('/admin/registration/<int:reg_id>/remark', methods=['PUT'])
def update_remark(reg_id):
    try:
        data = request.get_json()
        remark = data.get('remark', '')
        result = AdminService.update_remark(reg_id, remark)
        return jsonify(result)
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@admin_bp.route('/admin/get-async-routes', methods=['GET'])
def get_async_routes():
    """Endpoint for frontend router initialization. Returns empty list for static routes."""
    return jsonify({
        "success": True,
        "data": []
    })
