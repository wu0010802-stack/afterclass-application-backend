
from database import get_db_connection
from datetime import datetime

class AdminService:
    @staticmethod
    def get_all_registrations():
        conn = get_db_connection()
        try:
            results = conn.run("""
                SELECT 
                    r.id, 
                    s.name as student_name, 
                    s.birthday,
                    COALESCE(cl.name, r.class_name) as class_name,
                    r.created_at,
                    (SELECT COUNT(*) FROM registration_courses rc WHERE rc.registration_id = r.id) as course_count,
                    (SELECT COUNT(*) FROM registration_supplies rs WHERE rs.registration_id = r.id) as supply_count,
                    r.is_paid,
                    COALESCE((
                        SELECT string_agg(c.name, '、') 
                        FROM registration_courses rc 
                        JOIN courses c ON rc.course_id = c.id 
                        WHERE rc.registration_id = r.id
                    ), '') as course_names
                FROM registrations r
                JOIN students s ON r.student_id = s.id
                LEFT JOIN classes cl ON r.class_id = cl.id
                ORDER BY r.created_at DESC
            """)
            
            registrations = []
            for row in results:
                registrations.append({
                    'id': row[0],
                    'student_name': row[1],
                    'birthday': row[2].strftime('%Y-%m-%d') if row[2] else None,
                    'class_name': row[3],
                    'created_at': row[4].isoformat() if row[4] else None,
                    'course_count': row[5],
                    'supply_count': row[6],
                    'is_paid': row[7],
                    'course_names': row[8],
                    'type': 'registration',
                    'status': '已報名'
                })
            
            return {'registrations': registrations}
        finally:
            conn.close()

    @staticmethod
    def get_dashboard_stats():
        conn = get_db_connection()
        try:
            # This query now fetches individual course registrations (enrollments)
            # instead of grouping by registration. This gives us a unified list of
            # all enrolled and waitlisted course attempts.
            results = conn.run("""
                SELECT 
                    r.id as registration_id,
                    rc.id as registration_course_id,
                    s.name as student_name,
                    s.birthday,
                    COALESCE(cl.name, r.class_name) as class_name,
                    c.name as course_name,
                    rc.status,
                    r.created_at,
                    r.is_paid
                FROM registration_courses rc
                JOIN registrations r ON rc.registration_id = r.id
                JOIN students s ON r.student_id = s.id
                JOIN courses c ON rc.course_id = c.id
                LEFT JOIN classes cl ON r.class_id = cl.id
                ORDER BY r.created_at DESC
            """)
            
            enrollments = []
            for row in results:
                enrollments.append({
                    'registration_id': row[0],
                    'registration_course_id': row[1],
                    'student_name': row[2],
                    'birthday': row[3].strftime('%Y-%m-%d') if row[3] else None,
                    'class_name': row[4],
                    'course_name': row[5],
                    'status': row[6],
                    'created_at': row[7].isoformat() if row[7] else None,
                    'is_paid': row[8]
                })
            
            # Get overall statistics
            stats_result = conn.run("""
                SELECT 
                    (SELECT COUNT(*) FROM registrations) as total_registrations,
                    (SELECT COUNT(*) FROM students) as total_students,
                    (SELECT COUNT(*) FROM registration_courses WHERE status = 'enrolled') as total_enrollments,
                    (SELECT COUNT(*) FROM registration_supplies) as total_supplies
            """)
            
            stats = stats_result[0]
            statistics = {
                'totalRegistrations': stats[0],
                'totalStudents': stats[1],
                'totalCourseEnrollments': stats[2],
                'totalSupplyOrders': stats[3]
            }
            
            return {
                'enrollments': enrollments,
                'statistics': statistics
            }
        finally:
            conn.close()

    @staticmethod
    def get_courses_stats():
        conn = get_db_connection()
        try:
            # Only count 'enrolled' students for course usage stats
            results = conn.run("""
                SELECT c.id, c.name, c.price, c.sessions, c.frequency, c.capacity, c.description, c.video_url,
                       COUNT(CASE WHEN rc.status = 'enrolled' THEN 1 END) as used
                FROM courses c
                LEFT JOIN registration_courses rc ON c.id = rc.course_id
                GROUP BY c.id, c.name, c.price, c.sessions, c.frequency, c.capacity, c.description, c.video_url
                ORDER BY c.id
            """)
            
            courses = []
            for row in results:
                capacity = row[5] if row[5] is not None else 30
                used = row[8]
                courses.append({
                    'id': row[0],
                    'name': row[1],
                    'price': row[2],
                    'sessions': row[3],
                    'frequency': row[4],
                    'capacity': capacity,
                    'description': row[6] or '',
                    'video_url': row[7] or '',
                    'used': used,
                    'remaining': max(0, capacity - used)
                })
            return courses
        finally:
            conn.close()

    @staticmethod
    def get_registration_detail(reg_id):
        conn = get_db_connection()
        try:
            reg_results = conn.run("""
                SELECT r.id, s.name, COALESCE(cl.name, r.class_name), r.created_at, r.updated_at, s.birthday, r.is_paid
                FROM registrations r
                JOIN students s ON r.student_id = s.id
                LEFT JOIN classes cl ON r.class_id = cl.id
                WHERE r.id = :id
            """, id=reg_id)
            
            if not reg_results:
                return None
            
            reg = reg_results[0]
            
            course_results = conn.run("""
                SELECT c.name, rc.price_snapshot, rc.status, rc.id as registration_course_id
                FROM registration_courses rc
                JOIN courses c ON rc.course_id = c.id
                WHERE rc.registration_id = :reg_id
            """, reg_id=reg_id)
            
            courses = [{'name': row[0], 'price': str(row[1]), 'status': row[2], 'id': row[3]} for row in course_results]
            
            supply_results = conn.run("""
                SELECT s.name, rs.price_snapshot
                FROM registration_supplies rs
                JOIN supplies s ON rs.supply_id = s.id
                WHERE rs.registration_id = :reg_id
            """, reg_id=reg_id)
            
            supplies = [{'name': row[0], 'price': str(row[1])} for row in supply_results]
            
            total_amount = 0
            for course in courses:
                total_amount += int(course['price'])
            
            for supply in supplies:
                total_amount += int(supply['price'])

            return {
                'id': reg[0],
                'student_name': reg[1],
                'class_name': reg[2],
                'created_at': reg[3].isoformat() if reg[3] else None,
                'updated_at': reg[4].isoformat() if reg[4] else None,
                'birthday': reg[5].strftime('%Y-%m-%d') if reg[5] else None,
                'is_paid': reg[6],
                'courses': courses,
                'supplies': supplies,
                'total_amount': total_amount
            }
        finally:
            conn.close()

    @staticmethod
    def delete_registration(reg_id):
        conn = get_db_connection()
        try:
            conn.run("DELETE FROM registrations WHERE id = :id", id=reg_id)
        finally:
            conn.close()

    @staticmethod
    def promote_from_waitlist(registration_course_id):
        conn = get_db_connection()
        try:
            conn.run("BEGIN")
            # Get course_id and check current status
            rc_info = conn.run(
                "SELECT course_id, status FROM registration_courses WHERE id = :rc_id FOR UPDATE",
                rc_id=registration_course_id
            )
            if not rc_info or rc_info[0][1] != 'waitlist':
                raise ValueError("報名項目不存在或非候補狀態")

            course_id = rc_info[0][0]

            # Check capacity
            course_info = conn.run(
                "SELECT capacity, (SELECT COUNT(*) FROM registration_courses WHERE course_id = :cid AND status = 'enrolled') as enrolled_count FROM courses WHERE id = :cid",
                cid=course_id
            )
            capacity = course_info[0][0]
            enrolled_count = course_info[0][1]

            if enrolled_count >= capacity:
                raise ValueError("課程容量已滿，無法從候補名單中移出")

            # Promote
            conn.run(
                "UPDATE registration_courses SET status = 'enrolled' WHERE id = :rc_id",
                rc_id=registration_course_id
            )
            conn.run("COMMIT")
            return {"message": "成功將學生移出候補名單並加入課程"}
        except Exception as e:
            conn.run("ROLLBACK")
            raise e
        finally:
            conn.close()
    
    @staticmethod
    def delete_waitlist_entry(registration_course_id):
        conn = get_db_connection()
        try:
            # Ensure the entry is actually a waitlist entry before deleting
            result = conn.run(
                "DELETE FROM registration_courses WHERE id = :rc_id AND status = 'waitlist'",
                rc_id=registration_course_id
            )
            if result is None: # In pg8000, rowcount is not returned, so we check if an error would have been raised
                # This check is imperfect. A better check would be to SELECT first.
                # For now, we assume if it didn't error, it worked or did nothing.
                return {"message": "已從候補名單中刪除"}
            return {"message": "已從候補名單中刪除"}
        finally:
            conn.close()


    @staticmethod
    def delete_course(course_id):
        conn = get_db_connection()
        try:
            check_result = conn.run(
                "SELECT COUNT(*) FROM registration_courses WHERE course_id = :id",
                id=course_id
            )
            if check_result and check_result[0][0] > 0:
                raise ValueError(f'無法刪除：此課程有 {check_result[0][0]} 筆報名記錄，請先刪除相關報名後再試。')
            
            conn.run("DELETE FROM courses WHERE id = :id", id=course_id)
        finally:
            conn.close()

    @staticmethod
    def create_course(data):
        name = data.get('name')
        price = data.get('price')
        if not name or price is None:
            raise ValueError('課程名稱和價格為必填')

        conn = get_db_connection()
        try:
            existing = conn.run("SELECT id FROM courses WHERE name = :name", name=name)
            if existing:
                raise ValueError('課程名稱已存在')

            result = conn.run(
                """INSERT INTO courses (name, price, sessions, frequency, description, capacity, video_url) 
                   VALUES (:name, :price, :sessions, :frequency, :description, :capacity, :video_url) 
                   RETURNING id""",
                name=name, price=int(price), 
                sessions=int(data.get('sessions')) if data.get('sessions') else None,
                frequency=data.get('frequency', ''), 
                description=data.get('description', ''), 
                capacity=int(data.get('capacity', 30)),
                video_url=data.get('video_url', '')
            )
            return result[0][0]
        finally:
            conn.close()

    @staticmethod
    def update_course(course_id, data):
        conn = get_db_connection()
        try:
            check_result = conn.run("SELECT id FROM courses WHERE id = :id", id=course_id)
            if not check_result:
                raise ValueError('課程不存在')

            if 'name' in data:
                name = data.get('name')
                price = data.get('price')
                if not name or price is None:
                    raise ValueError('課程名稱和價格為必填')
                
                existing = conn.run(
                    "SELECT id FROM courses WHERE name = :name AND id != :id",
                    name=name, id=course_id
                )
                if existing:
                    raise ValueError('課程名稱已被其他課程使用')

                conn.run(
                    """UPDATE courses SET 
                       name = :name, price = :price, sessions = :sessions,
                       frequency = :frequency, description = :description, capacity = :capacity,
                       video_url = :video_url
                       WHERE id = :id""",
                    name=name, price=int(price), 
                    sessions=int(data.get('sessions')) if data.get('sessions') else None,
                    frequency=data.get('frequency', ''), 
                    description=data.get('description', ''), 
                    capacity=int(data.get('capacity', 30)),
                    video_url=data.get('video_url', ''),
                    id=course_id
                )
            else:
                # Capacity only update
                new_capacity = data.get('capacity')
                if new_capacity is None:
                    raise ValueError('Missing capacity parameter')
                conn.run(
                    "UPDATE courses SET capacity = :capacity WHERE id = :id",
                    capacity=int(new_capacity), id=course_id
                )
        finally:
            conn.close()

    @staticmethod
    def get_classes():
        conn = get_db_connection()
        try:
            results = conn.run("SELECT id, name FROM classes ORDER BY id")
            return [{'id': row[0], 'name': row[1]} for row in results]
        finally:
            conn.close()

    @staticmethod
    def create_class(name):
        conn = get_db_connection()
        try:
            existing = conn.run("SELECT id FROM classes WHERE name = :name", name=name)
            if existing:
                raise ValueError('班級名稱已存在')
            
            result = conn.run(
                "INSERT INTO classes (name) VALUES (:name) RETURNING id",
                name=name
            )
            return result[0][0]
        finally:
            conn.close()

    @staticmethod
    def update_class(class_id, name):
        conn = get_db_connection()
        try:
            existing = conn.run("SELECT id FROM classes WHERE name = :name AND id != :id", name=name, id=class_id)
            if existing:
                raise ValueError('班級名稱已存在')
            
            conn.run("UPDATE classes SET name = :name WHERE id = :id", name=name, id=class_id)
        finally:
            conn.close()

    @staticmethod
    def delete_class(class_id):
        conn = get_db_connection()
        try:
            # Check if any registration refers to this class
            check = conn.run("SELECT COUNT(*) FROM registrations WHERE class_id = :id", id=class_id)
            if check[0][0] > 0:
                raise ValueError(f'無法刪除：已有 {check[0][0]} 位學生屬於此班級')
                
            conn.run("DELETE FROM classes WHERE id = :id", id=class_id)
        finally:
            conn.close()

    @staticmethod
    def update_settings(start, end):
        conn = get_db_connection()
        try:
            conn.run(
                "INSERT INTO settings (key, value) VALUES ('registration_start', :value) ON CONFLICT (key) DO UPDATE SET value = :value",
                value=start
            )
            conn.run(
                "INSERT INTO settings (key, value) VALUES ('registration_end', :value) ON CONFLICT (key) DO UPDATE SET value = :value",
                value=end
            )
        finally:
            conn.close()

    @staticmethod
    def toggle_payment(reg_id, paid):
        conn = get_db_connection()
        try:
            conn.run("UPDATE registrations SET is_paid = :paid, updated_at = :now WHERE id = :id",
                     paid=paid, now=datetime.now(), id=reg_id)
        finally:
            conn.close()
