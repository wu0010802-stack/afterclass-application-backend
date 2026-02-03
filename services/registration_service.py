
from database import get_db_connection
from datetime import datetime
import json

class RegistrationService:
    @staticmethod
    def get_registration_by_student(student_name, birthday=None):
        conn = get_db_connection()
        try:
            # Get latest registration for student
            # Join with classes table to get class name via ID, fallback to class_name column if ID is null (migration safety)
            query = """
                SELECT r.id, s.name, COALESCE(cl.name, r.class_name), r.created_at, s.birthday
                FROM registrations r
                JOIN students s ON r.student_id = s.id
                LEFT JOIN classes cl ON r.class_id = cl.id
                WHERE s.name = :name
            """
            
            params = {'name': student_name}
            
            if birthday:
                query += " AND s.birthday = :birthday"
                params['birthday'] = birthday
                
            query += """
                ORDER BY r.created_at DESC
                LIMIT 1
            """
            
            results = conn.run(query, **params)
            
            if not results:
                return None
            
            reg = results[0]
            reg_id = reg[0]
            
            # Get courses
            course_results = conn.run("""
                SELECT c.name, c.price
                FROM registration_courses rc
                JOIN courses c ON rc.course_id = c.id
                WHERE rc.registration_id = :reg_id
            """, reg_id=reg_id)
            
            courses = [{'name': row[0], 'price': str(row[1])} for row in course_results]
            
            # Get supplies
            supply_results = conn.run("""
                SELECT s.name, s.price
                FROM registration_supplies rs
                JOIN supplies s ON rs.supply_id = s.id
                WHERE rs.registration_id = :reg_id
            """, reg_id=reg_id)
            
            supplies = [{'name': row[0], 'price': str(row[1])} for row in supply_results]
            
            birthday_str = reg[4].strftime('%Y-%m-%d') if reg[4] else ''

            return {
                'id': reg_id,
                'name': reg[1],
                'birthday': birthday_str,
                'class': reg[2] or 'Unspecified',
                'courses': courses,
                'supplies': supplies,
                'totalItems': len(courses) + len(supplies)
            }
        finally:
            conn.close()

    @staticmethod
    def handle_registration(data, update=False):
        name = data.get('name')
        birthday = data.get('birthday')  # Format: YYYY-MM-DD
        class_name = data.get('class')
        courses = data.get('courses', [])
        supplies = data.get('supplies', [])
        
        # Auto-add material fee if elite English course is selected
        has_elite_english = any(c.get('name') == '菁英美語 (限大班)' for c in courses)
        has_material_fee = any(c.get('name') == '菁英美語教材費' for c in courses)
        
        if has_elite_english and not has_material_fee:
            courses.append({
                'name': '菁英美語教材費',
                'price': '1500'
            })
        
        conn = get_db_connection()
        try:
            conn.run("BEGIN")
            current_time = datetime.now()
            
            if update:
                reg_id = data.get('id')
                if not reg_id:
                    raise ValueError("Missing ID for update")
                
                # Fetch student_id
                student_res = conn.run("SELECT student_id FROM registrations WHERE id=:id", id=reg_id)
                if student_res:
                    student_id = student_res[0][0]
                    # Update student birthday if provided
                    if birthday:
                         conn.run("UPDATE students SET birthday=:birthday WHERE id=:id", birthday=birthday, id=student_id)

                # Resolve class_id
                class_id = None
                if class_name:
                    # Try to find class_id
                    res = conn.run("SELECT id FROM classes WHERE name = :name", name=class_name)
                    if res:
                        class_id = res[0][0]
                    else:
                        # Auto-create class if not exists (optional, but good for stability)
                        res = conn.run("INSERT INTO classes (name) VALUES (:name) RETURNING id", name=class_name)
                        class_id = res[0][0]

                conn.run(
                    "UPDATE registrations SET class_name=:class_name, class_id=:class_id, updated_at=:now WHERE id=:id",
                    class_name=class_name, class_id=class_id, now=current_time, id=reg_id
                )
                
                conn.run("DELETE FROM registration_courses WHERE registration_id=:id", id=reg_id)
                conn.run("DELETE FROM registration_supplies WHERE registration_id=:id", id=reg_id)
                new_id = reg_id
                message = 'Update successful!'
            else:
                # Insert or get student
                # 3NF Optimization: Identify student by Name + Birthday
                student_result = conn.run(
                    "SELECT id FROM students WHERE name=:name AND birthday=:birthday", 
                    name=name, birthday=birthday
                )
                if student_result:
                    student_id = student_result[0][0]
                else:
                    student_result = conn.run(
                        "INSERT INTO students (name, birthday) VALUES (:name, :birthday) RETURNING id",
                        name=name, birthday=birthday
                    )
                    student_id = student_result[0][0]
                
                # Resolve class_id
                class_id = None
                if class_name:
                    res = conn.run("SELECT id FROM classes WHERE name = :name", name=class_name)
                    if res:
                        class_id = res[0][0]
                    else:
                         # Auto-create class if not exists
                        res = conn.run("INSERT INTO classes (name) VALUES (:name) RETURNING id", name=class_name)
                        class_id = res[0][0]
                
                # Create registration
                reg_result = conn.run(
                    "INSERT INTO registrations (student_id, class_name, class_id, created_at, updated_at) VALUES (:student_id, :class_name, :class_id, :now, :now) RETURNING id",
                    student_id=student_id, class_name=class_name, class_id=class_id, now=current_time
                )
                new_id = reg_result[0][0]
                message = 'Registration successful!'

            # Insert courses with capacity check
            waitlisted_courses = []
            for course in courses:
                # Get price for snapshot
                course_result = conn.run("SELECT id, capacity, price FROM courses WHERE name=:name FOR UPDATE", name=course['name'])
                
                if course_result:
                    course_id = course_result[0][0]
                    capacity = course_result[0][1]
                    price_snapshot = course_result[0][2]
                    status = 'enrolled'
                    
                    if capacity is not None:
                        # Only count ENROLLED students
                        count_result = conn.run(
                            "SELECT COUNT(*) FROM registration_courses WHERE course_id=:cid AND status='enrolled'", 
                            cid=course_id
                        )
                        current_count = count_result[0][0]
                        
                        if current_count >= capacity:
                            status = 'waitlist'
                            waitlisted_courses.append(course['name'])

                    conn.run(
                        "INSERT INTO registration_courses (registration_id, course_id, status, price_snapshot) VALUES (:reg_id, :course_id, :status, :price)",
                        reg_id=new_id, course_id=course_id, status=status, price=price_snapshot
                    )
            
            # Insert supplies
            for supply in supplies:
                # Get price for snapshot
                supply_result = conn.run("SELECT id, price FROM supplies WHERE name=:name", name=supply['name'])
                if supply_result:
                    supply_id = supply_result[0][0]
                    price_snapshot = supply_result[0][1]
                    conn.run(
                        "INSERT INTO registration_supplies (registration_id, supply_id, price_snapshot) VALUES (:reg_id, :supply_id, :price)",
                        reg_id=new_id, supply_id=supply_id, price=price_snapshot
                    )
            
            conn.run("COMMIT")
            
            if waitlisted_courses:
                waitlist_msg = "，但部分課程已額滿列入候補： " + "、".join(waitlisted_courses)
                return {'message': message + waitlist_msg, 'id': new_id, 'waitlisted': True}
            
            return {'message': message, 'id': new_id, 'waitlisted': False}
            
        except Exception as e:
            conn.run("ROLLBACK")
            raise e
        finally:
            conn.close()

    @staticmethod
    def get_course_availability():
        conn = get_db_connection()
        try:
            # Only count ENROLLED students as used
            results = conn.run("""
                SELECT c.name, c.capacity, COUNT(CASE WHEN rc.status = 'enrolled' THEN 1 END) as used
                FROM courses c
                LEFT JOIN registration_courses rc ON c.id = rc.course_id
                GROUP BY c.id, c.name, c.capacity
            """)
            
            availability = {}
            for row in results:
                name = row[0]
                capacity = row[1] if row[1] is not None else 30
                used = row[2]
                remaining = max(0, capacity - used)
                availability[name] = remaining
            return availability
        finally:
            conn.close()

    @staticmethod
    def get_registration_settings():
        conn = get_db_connection()
        try:
            results = conn.run("""
                SELECT key, value FROM settings 
                WHERE key IN ('registration_start', 'registration_end')
            """)
            
            settings = {}
            for row in results:
                settings[row[0]] = row[1]
            return {
                'start': settings.get('registration_start', ''),
                'end': settings.get('registration_end', '')
            }
        finally:
            conn.close()

    @staticmethod
    def get_course_videos():
        conn = get_db_connection()
        try:
            results = conn.run("SELECT name, video_url FROM courses WHERE video_url IS NOT NULL AND video_url != ''")
            return {row[0]: row[1] for row in results}
        finally:
            conn.close()

    @staticmethod
    def get_all_classes():
        conn = get_db_connection()
        try:
            results = conn.run("SELECT name FROM classes ORDER BY id")
            return [row[0] for row in results]
        finally:
            conn.close()
