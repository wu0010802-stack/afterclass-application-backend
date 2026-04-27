
from database import get_db_connection
from datetime import datetime, timedelta, timezone
import json

# Taiwan timezone (UTC+8)
TW_TZ = timezone(timedelta(hours=8))

def get_taiwan_time():
    """Get current time in Taiwan timezone"""
    return datetime.now(TW_TZ)

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
            
            # Compute waitlist position with a window function in a single query.
            # The window has to be computed across ALL rows for the course before
            # filtering by registration_id, so we wrap it in a subquery.
            course_results = conn.run("""
                SELECT name, price, status, waitlist_position
                FROM (
                    SELECT rc.registration_id, c.name, c.price, rc.status,
                           CASE WHEN rc.status = 'waitlist'
                                THEN ROW_NUMBER() OVER (
                                        PARTITION BY rc.course_id, rc.status
                                        ORDER BY rc.id
                                     )
                                ELSE NULL END AS waitlist_position
                    FROM registration_courses rc
                    JOIN courses c ON rc.course_id = c.id
                ) sub
                WHERE registration_id = :reg_id
            """, reg_id=reg_id)

            courses = []
            for row in course_results:
                course_data = {
                    'name': row[0],
                    'price': str(row[1]),
                    'status': row[2],
                }
                if row[2] == 'waitlist':
                    course_data['waitlist_position'] = row[3] or 1
                courses.append(course_data)
            
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
        # Time Validation
        # Server time should be used directly. Assuming server is configured to correct timezone or local time matches user intent.
        current_time = get_taiwan_time()
        settings_res = RegistrationService.get_registration_settings()
        start = settings_res.get('start')
        end = settings_res.get('end')

        if start:
            try:
                start_dt = datetime.fromisoformat(start)
                # Add timezone info if naive
                if start_dt.tzinfo is None:
                    start_dt = start_dt.replace(tzinfo=TW_TZ)
                if current_time < start_dt:
                    raise ValueError(f"報名尚未開始 (開放時間: {start})")
            except ValueError:
                pass # Ignore invalid date format in settings

        if end:
            try:
                end_dt = datetime.fromisoformat(end)
                # Add timezone info if naive
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=TW_TZ)
                if current_time > end_dt:
                    raise ValueError(f"報名已截止 (截止時間: {end})")
            except ValueError:
                pass

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
            current_time = get_taiwan_time()
            
            if update:
                reg_id = data.get('id')
                if not reg_id:
                    raise ValueError("Missing ID for update")
                
                # Fetch OLD data for comparison
                old_data = conn.run("""
                    SELECT s.name, r.class_name, s.birthday,
                           (SELECT string_agg(c.name, '、') FROM registration_courses rc 
                            JOIN courses c ON rc.course_id = c.id WHERE rc.registration_id = r.id) as old_courses,
                           (SELECT string_agg(sp.name, '、') FROM registration_supplies rs
                            JOIN supplies sp ON rs.supply_id = sp.id WHERE rs.registration_id = r.id) as old_supplies
                    FROM registrations r
                    JOIN students s ON r.student_id = s.id
                    WHERE r.id = :id
                """, id=reg_id)
                
                old_student_name = old_data[0][0] if old_data else ''
                old_class = old_data[0][1] if old_data else ''
                old_birthday = old_data[0][2].strftime('%Y-%m-%d') if old_data and old_data[0][2] else ''
                old_courses_str = old_data[0][3] if old_data and old_data[0][3] else ''
                old_supplies_str = old_data[0][4] if old_data and old_data[0][4] else ''
                
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
                
                # Build change descriptions
                changes = []
                new_courses_names = [c.get('name', '') for c in courses]
                new_supplies_names = [s.get('name', '') for s in supplies]
                new_courses_str = '、'.join(new_courses_names)
                new_supplies_str = '、'.join(new_supplies_names)
                
                if old_class != class_name:
                    changes.append(f"班級：{old_class or '無'} → {class_name}")
                if old_birthday != birthday:
                    changes.append(f"生日：{old_birthday or '無'} → {birthday}")
                if old_courses_str != new_courses_str:
                    changes.append(f"課程：{old_courses_str or '無'} → {new_courses_str or '無'}")
                if old_supplies_str != new_supplies_str:
                    changes.append(f"用品：{old_supplies_str or '無'} → {new_supplies_str or '無'}")
                
                # Record change if any
                if changes:
                    change_description = '；'.join(changes)
                    conn.run("""
                        INSERT INTO registration_changes (registration_id, student_name, change_type, change_description)
                        VALUES (:reg_id, :student_name, :change_type, :change_desc)
                    """, reg_id=reg_id, student_name=name or old_student_name, change_type='前台修改', change_desc=change_description)
                
                message = '更新成功！'
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
                message = '報名成功！'

            # Pre-fetch all course metadata + current enrollment counts in ONE
            # query. Locks the course rows to prevent concurrent enrollment from
            # over-filling capacity. (Was 3 round-trips per course.)
            waitlisted_courses = []
            waitlisted_positions = {}
            course_names = [c['name'] for c in courses if c.get('name')]
            course_meta = {}
            if course_names:
                rows = conn.run("""
                    SELECT c.name, c.id, c.capacity, c.price,
                           COALESCE(c.allow_waitlist, TRUE) AS allow_waitlist,
                           (SELECT COUNT(*) FROM registration_courses rc
                              WHERE rc.course_id = c.id AND rc.status = 'enrolled') AS enrolled_count,
                           (SELECT COUNT(*) FROM registration_courses rc
                              WHERE rc.course_id = c.id AND rc.status = 'waitlist') AS waitlist_count
                    FROM courses c
                    WHERE c.name = ANY(:names)
                    FOR UPDATE OF c
                """, names=course_names)
                course_meta = {r[0]: {
                    'id': r[1], 'capacity': r[2], 'price': r[3],
                    'allow_waitlist': r[4], 'enrolled': r[5], 'waitlist': r[6],
                } for r in rows}

            for course in courses:
                meta = course_meta.get(course.get('name'))
                if not meta:
                    continue
                status = 'enrolled'
                capacity = meta['capacity']
                if capacity is not None and meta['enrolled'] >= capacity:
                    if meta['allow_waitlist']:
                        status = 'waitlist'
                        meta['waitlist'] += 1
                        waitlisted_courses.append(course['name'])
                        waitlisted_positions[course['name']] = meta['waitlist']
                    else:
                        raise ValueError(f"課程 {course['name']} 已額滿且不接受候補")
                else:
                    meta['enrolled'] += 1

                conn.run(
                    "INSERT INTO registration_courses (registration_id, course_id, status, price_snapshot) VALUES (:reg_id, :course_id, :status, :price)",
                    reg_id=new_id, course_id=meta['id'], status=status, price=meta['price'],
                )

            # Pre-fetch supply metadata in one query, then insert.
            supply_names = [s['name'] for s in supplies if s.get('name')]
            if supply_names:
                supply_rows = conn.run(
                    "SELECT name, id, price FROM supplies WHERE name = ANY(:names)",
                    names=supply_names,
                )
                supply_meta = {r[0]: (r[1], r[2]) for r in supply_rows}
                for supply in supplies:
                    found = supply_meta.get(supply.get('name'))
                    if found:
                        supply_id, price_snapshot = found
                        conn.run(
                            "INSERT INTO registration_supplies (registration_id, supply_id, price_snapshot) VALUES (:reg_id, :supply_id, :price)",
                            reg_id=new_id, supply_id=supply_id, price=price_snapshot,
                        )
            
            conn.run("COMMIT")
            
            if waitlisted_courses:
                # Build message with positions
                waitlist_details = []
                for course_name in waitlisted_courses:
                    pos = waitlisted_positions.get(course_name, '?')
                    waitlist_details.append(f"{course_name} (第{pos}位)")
                waitlist_msg = "，但部分課程已額滿列入候補：" + "、".join(waitlist_details)
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
                SELECT c.name, c.capacity, c.allow_waitlist, COUNT(CASE WHEN rc.status = 'enrolled' THEN 1 END) as used
                FROM courses c
                LEFT JOIN registration_courses rc ON c.id = rc.course_id
                GROUP BY c.id, c.name, c.capacity, c.allow_waitlist
            """)
            
            availability = {}
            for row in results:
                name = row[0]
                capacity = row[1] if row[1] is not None else 30
                allow_waitlist = row[2] if row[2] is not None else True
                used = row[3]
                remaining = max(0, capacity - used)
                
                # If no remaining spots and no waitlist allowed, send specific signal
                if remaining == 0 and not allow_waitlist:
                     availability[name] = -1 # -1 indicates FULL and NO WAITLIST
                else:
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
