
from database import get_db_connection
from datetime import datetime, timedelta, timezone

# Taiwan timezone (UTC+8)
TW_TZ = timezone(timedelta(hours=8))

def get_taiwan_time():
    """Get current time in Taiwan timezone"""
    return datetime.now(TW_TZ)

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
                        SELECT string_agg(
                            CASE 
                                WHEN rc.status = 'waitlist' THEN 
                                    c.name || ' (候補順位: ' || (
                                        SELECT COUNT(*) + 1
                                        FROM registration_courses rc2
                                        WHERE rc2.course_id = rc.course_id
                                          AND rc2.status = 'waitlist'
                                          AND rc2.id < rc.id
                                    ) || ')'
                                ELSE c.name 
                            END, 
                            '、'
                        ) 
                        FROM registration_courses rc 
                        JOIN courses c ON rc.course_id = c.id 
                        WHERE rc.registration_id = r.id
                    ), '') as course_names,
                    r.remark
                FROM registrations r
                JOIN students s ON r.student_id = s.id
                LEFT JOIN classes cl ON r.class_id = cl.id
                ORDER BY r.created_at ASC
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
                    'remark': row[9] or '',
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
            current_date = get_taiwan_time().date()
            # Stats Summary
            summary_query = """
                SELECT 
                    (SELECT COUNT(*) FROM registrations) as total_registrations,
                    (SELECT COUNT(*) FROM students) as total_students,
                    (SELECT COUNT(*) FROM registration_courses WHERE status = 'enrolled') as total_enrollments,
                    (SELECT COUNT(*) FROM registration_courses WHERE status = 'waitlist') as total_waitlist,
                    (SELECT COUNT(*) FROM registration_supplies) as total_supplies,
                    (SELECT COUNT(*) FROM registrations WHERE DATE(created_at) = :today) as today_new,
                    (SELECT SUM(capacity) FROM courses) as total_capacity
            """
            summary_res = conn.run(summary_query, today=current_date)[0]
            
            # Revenue Calculation
            # 1. Course Revenue
            course_rev = conn.run("""
                SELECT 
                    SUM(CASE WHEN r.is_paid IS TRUE THEN c.price ELSE 0 END) as paid,
                    SUM(CASE WHEN r.is_paid IS NOT TRUE THEN c.price ELSE 0 END) as unpaid
                FROM registration_courses rc 
                JOIN registrations r ON rc.registration_id = r.id
                JOIN courses c ON rc.course_id = c.id
                WHERE rc.status = 'enrolled'
            """)[0]
            
            # 2. Supply Revenue
            supply_rev = conn.run("""
                SELECT 
                    SUM(CASE WHEN r.is_paid IS TRUE THEN s.price ELSE 0 END) as paid,
                    SUM(CASE WHEN r.is_paid IS NOT TRUE THEN s.price ELSE 0 END) as unpaid
                FROM registration_supplies rs
                JOIN registrations r ON rs.registration_id = r.id
                JOIN supplies s ON rs.supply_id = s.id
            """)[0]
            
            total_revenue = (course_rev[0] or 0) + (supply_rev[0] or 0)
            total_unpaid = (course_rev[1] or 0) + (supply_rev[1] or 0)
            
            # Calculate Enrollment Rate
            total_enrollments = summary_res[2]
            total_capacity = summary_res[6]
            enrollment_rate = 0
            if total_capacity and total_capacity > 0:
                enrollment_rate = round((total_enrollments / total_capacity) * 100, 1)

            # Daily Registrations
            daily_res = conn.run("""
                SELECT DATE(created_at) as d, COUNT(*) as c
                FROM registrations
                GROUP BY DATE(created_at)
                ORDER BY DATE(created_at)
            """)
            daily_stats = [{'date': row[0], 'count': row[1]} for row in daily_res]
            
            # Top Courses
            top_courses_res = conn.run("""
                SELECT c.name, COUNT(*) as c
                FROM registration_courses rc
                JOIN courses c ON rc.course_id = c.id
                WHERE rc.status = 'enrolled'
                GROUP BY c.name
                ORDER BY c DESC
                LIMIT 5
            """)
            top_courses = [{'name': row[0], 'count': row[1]} for row in top_courses_res]
            
            return {
                'statistics': {
                    'totalRegistrations': summary_res[0],
                    'totalStudents': summary_res[1],
                    'totalCourseEnrollments': summary_res[2],
                    'totalWaitlist': summary_res[3],
                    'totalSupplyOrders': summary_res[4],
                    'todayNewRegistrations': summary_res[5],
                    'totalRevenue': total_revenue,
                    'totalUnpaid': total_unpaid,
                    'enrollmentRate': enrollment_rate
                },
                'charts': {
                    'daily': daily_stats,
                    'topCourses': top_courses
                }
            }
        finally:
            conn.close()

    @staticmethod
    def get_courses_stats():
        conn = get_db_connection()
        try:
            # Stats for enrolled and waitlist
            results = conn.run("""
                SELECT c.id, c.name, c.price, c.sessions, c.frequency, c.capacity, c.description, c.video_url, c.allow_waitlist,
                       COUNT(CASE WHEN rc.status = 'enrolled' THEN 1 END) as used,
                       COUNT(CASE WHEN rc.status = 'waitlist' THEN 1 END) as waitlist_count
                FROM courses c
                LEFT JOIN registration_courses rc ON c.id = rc.course_id
                GROUP BY c.id, c.name, c.price, c.sessions, c.frequency, c.capacity, c.description, c.video_url, c.allow_waitlist
                ORDER BY c.id
            """)
            
            courses = []
            for row in results:
                capacity = row[5] if row[5] is not None else 30
                used = row[9]
                waitlist_count = row[10]
                courses.append({
                    'id': row[0],
                    'name': row[1],
                    'price': row[2],
                    'sessions': row[3],
                    'frequency': row[4],
                    'capacity': capacity,
                    'description': row[6] or '',
                    'video_url': row[7] or '',
                    'allow_waitlist': row[8] if row[8] is not None else True,
                    'used': used,
                    'waitlist_count': waitlist_count,
                    'remaining': max(0, capacity - used)
                })
            return courses
        finally:
            conn.close()
    def get_registration_detail(reg_id):
        conn = get_db_connection()
        try:
            reg_results = conn.run("""
                SELECT r.id, s.name, COALESCE(cl.name, r.class_name), r.created_at, r.updated_at, s.birthday, r.is_paid, r.remark
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
                if course['status'] == 'enrolled':
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
                'remark': reg[7] or '',
                'courses': courses,
                'supplies': supplies,
                'total_amount': total_amount
            }
        finally:
            conn.close()

    @staticmethod
    def update_remark(reg_id, remark):
        conn = get_db_connection()
        try:
            conn.run("UPDATE registrations SET remark = :remark, updated_at = :now WHERE id = :id",
                     remark=remark, now=get_taiwan_time(), id=reg_id)
            conn.run("COMMIT")
            return {'message': 'Remark updated'}
        finally:
            conn.close()

    @staticmethod
    def delete_registration(reg_id):
        conn = get_db_connection()
        try:
            conn.run("BEGIN")
            
            # First, get all courses this registration was enrolled in (not waitlist)
            enrolled_courses = conn.run("""
                SELECT course_id FROM registration_courses 
                WHERE registration_id = :reg_id AND status = 'enrolled'
            """, reg_id=reg_id)
            
            course_ids = [row[0] for row in enrolled_courses]
            
            # Delete the registration (cascades to registration_courses and registration_supplies)
            conn.run("DELETE FROM registrations WHERE id = :id", id=reg_id)
            
            # For each course that had an enrolled student, try to promote the next waitlisted person
            for course_id in course_ids:
                # Check if there's capacity now
                capacity_info = conn.run("""
                    SELECT c.capacity, 
                           (SELECT COUNT(*) FROM registration_courses WHERE course_id = :cid AND status = 'enrolled') as enrolled
                    FROM courses c WHERE c.id = :cid
                """, cid=course_id)
                
                if capacity_info:
                    capacity = capacity_info[0][0]
                    enrolled_count = capacity_info[0][1]
                    
                    # If there's now room, promote the first waitlisted person (by id order, which is chronological)
                    if capacity is None or enrolled_count < capacity:
                        # Find the first waitlisted entry for this course
                        waitlist_entry = conn.run("""
                            SELECT id FROM registration_courses 
                            WHERE course_id = :cid AND status = 'waitlist'
                            ORDER BY id ASC
                            LIMIT 1
                        """, cid=course_id)
                        
                        if waitlist_entry:
                            # Promote this entry
                            conn.run("""
                                UPDATE registration_courses SET status = 'enrolled' 
                                WHERE id = :rc_id
                            """, rc_id=waitlist_entry[0][0])
            
            conn.run("COMMIT")
        except Exception as e:
            conn.run("ROLLBACK")
            raise e
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
                # For now, we assume if it didn't error, it worked or did nothing.
                conn.run("COMMIT")
                return {"message": "已從候補名單中刪除"}
            conn.run("COMMIT")
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
            conn.run("COMMIT")
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
                """INSERT INTO courses (name, price, sessions, frequency, description, capacity, video_url, allow_waitlist) 
                   VALUES (:name, :price, :sessions, :frequency, :description, :capacity, :video_url, :allow_waitlist) 
                   RETURNING id""",
                name=name, price=int(price), 
                sessions=int(data.get('sessions')) if data.get('sessions') else None,
                frequency=data.get('frequency', ''), 
                description=data.get('description', ''), 
                capacity=int(data.get('capacity', 30)),
                video_url=data.get('video_url', ''),
                allow_waitlist=data.get('allow_waitlist', True)
            )
            conn.run("COMMIT")
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
                       video_url = :video_url, allow_waitlist = :allow_waitlist
                       WHERE id = :id""",
                    name=name, price=int(price), 
                    sessions=int(data.get('sessions')) if data.get('sessions') else None,
                    frequency=data.get('frequency', ''), 
                    description=data.get('description', ''), 
                    capacity=int(data.get('capacity', 30)),
                    video_url=data.get('video_url', ''),
                    allow_waitlist=data.get('allow_waitlist', True),
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
            conn.run("COMMIT")
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
            conn.run("COMMIT")
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
            conn.run("COMMIT")
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
            conn.run("COMMIT")
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
            conn.run("COMMIT")
        finally:
            conn.close()

    @staticmethod
    def toggle_payment(reg_id, paid):
        conn = get_db_connection()
        try:
            conn.run("UPDATE registrations SET is_paid = :paid, updated_at = :now WHERE id = :id",
                     paid=paid, now=get_taiwan_time(), id=reg_id)
            conn.run("COMMIT")
        finally:
            conn.close()

    @staticmethod
    def update_registration(reg_id, data):
        conn = get_db_connection()
        try:
            conn.run("BEGIN")
            
            # First check if registration exists
            check = conn.run("SELECT id, student_id FROM registrations WHERE id = :id", id=reg_id)
            if not check:
                raise ValueError("報名資料不存在")
            
            student_id = check[0][1]
            
            # Update student name if provided
            if 'student_name' in data:
                conn.run("UPDATE students SET name = :name WHERE id = :id",
                         name=data['student_name'], id=student_id)
            
            # Update student birthday if provided
            if 'birthday' in data and data['birthday']:
                conn.run("UPDATE students SET birthday = :birthday WHERE id = :id",
                         birthday=data['birthday'], id=student_id)
            
            # Update class if provided
            class_id = None
            if 'class_name' in data:
                class_name = data['class_name']
                if class_name:
                    # Try to find existing class
                    class_res = conn.run("SELECT id FROM classes WHERE name = :name", name=class_name)
                    if class_res:
                        class_id = class_res[0][0]
                    else:
                        # Create new class
                        class_res = conn.run("INSERT INTO classes (name) VALUES (:name) RETURNING id", name=class_name)
                        class_id = class_res[0][0]
                
                conn.run("UPDATE registrations SET class_name = :class_name, class_id = :class_id, updated_at = :now WHERE id = :id",
                         class_name=class_name, class_id=class_id, now=get_taiwan_time(), id=reg_id)
            
            # Update courses if provided
            if 'courses' in data:
                courses = data['courses']
                # Delete existing courses
                conn.run("DELETE FROM registration_courses WHERE registration_id = :reg_id", reg_id=reg_id)
                
                # Insert new courses
                for course in courses:
                    course_name = course.get('name')
                    if course_name:
                        course_res = conn.run("SELECT id, price FROM courses WHERE name = :name", name=course_name)
                        if course_res:
                            course_id = course_res[0][0]
                            price = course_res[0][1]
                            conn.run("""
                                INSERT INTO registration_courses (registration_id, course_id, status, price_snapshot) 
                                VALUES (:reg_id, :course_id, 'enrolled', :price)
                            """, reg_id=reg_id, course_id=course_id, price=price)
            
            # Update supplies if provided
            if 'supplies' in data:
                supplies = data['supplies']
                # Delete existing supplies
                conn.run("DELETE FROM registration_supplies WHERE registration_id = :reg_id", reg_id=reg_id)
                
                # Insert new supplies
                for supply in supplies:
                    supply_name = supply.get('name')
                    if supply_name:
                        supply_res = conn.run("SELECT id, price FROM supplies WHERE name = :name", name=supply_name)
                        if supply_res:
                            supply_id = supply_res[0][0]
                            price = supply_res[0][1]
                            conn.run("""
                                INSERT INTO registration_supplies (registration_id, supply_id, price_snapshot) 
                                VALUES (:reg_id, :supply_id, :price)
                            """, reg_id=reg_id, supply_id=supply_id, price=price)
            
            conn.run("COMMIT")
            return {'message': '更新成功'}
        except Exception as e:
            conn.run("ROLLBACK")
            raise e
        finally:
            conn.close()
