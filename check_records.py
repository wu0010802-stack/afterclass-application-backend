
from database import get_db_connection

def check_records():
    conn = get_db_connection()
    try:
        results = conn.run("SELECT r.id, s.name, r.class_name FROM registrations r JOIN students s ON r.student_id = s.id WHERE r.id IN (36, 37)")
        for row in results:
            print(f"ID: {row[0]}, Name: {row[1]}, Class: {row[2]}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    check_records()
