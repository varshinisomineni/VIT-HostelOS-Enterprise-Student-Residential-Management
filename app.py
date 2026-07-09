from flask import Flask, render_template, request, redirect, session, jsonify, make_response
from werkzeug.utils import secure_filename
from database import db, Menu, Complaint, Admin, Student, Attendance, LeaveRequest, RoomIssue, Parent, Notification, AUTHORITY_ROLES, ISSUE_TYPES
import os
import csv
import io
from datetime import datetime, date

app = Flask(__name__)

app.secret_key = "hostel_secret"

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///hostel.db'
app.config['UPLOAD_FOLDER'] = 'static/uploads/menu_images'
app.config['COMPLAINT_UPLOAD_FOLDER'] = 'static/uploads/complaint_images'
app.config['LEAVE_UPLOAD_FOLDER'] = 'static/uploads/leave_images'
app.config['ROOM_ISSUE_UPLOAD_FOLDER'] = 'static/uploads/room_issue_images'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Create upload folders if they don't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['COMPLAINT_UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['LEAVE_UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['ROOM_ISSUE_UPLOAD_FOLDER'], exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

db.init_app(app)

def migrate_db_columns():
    from sqlalchemy import inspect, text
    inspector = inspect(db.engine)

    table_migrations = {
        'complaint': [
            ('day', 'VARCHAR(50)'),
            ('feedback_date', 'DATE'),
            ('feedback_time', 'VARCHAR(20)'),
            ('image_filename', 'VARCHAR(200)'),
            ('submitted_at', 'DATETIME'),
            ('student_id', 'INTEGER'),
            ('forwarded_to_chief', 'BOOLEAN'),
            ('forwarded_at', 'DATETIME'),
            ('solved_at', 'DATETIME'),
            ('rating', 'INTEGER'),
            ('rating_comment', 'TEXT'),
            ('solution_note', 'TEXT'),
        ],
        'student': [
            ('username', 'VARCHAR(100)'),
            ('password', 'VARCHAR(100)'),
            ('security_question_1', 'VARCHAR(100)'),
            ('security_answer_1', 'VARCHAR(100)'),
            ('security_question_2', 'VARCHAR(100)'),
            ('security_answer_2', 'VARCHAR(100)'),
            ('parent_email', 'VARCHAR(100)'),
            ('class_incharge_email', 'VARCHAR(100)'),
        ],
        'admin': [
            ('role', 'VARCHAR(50)'),
        ],
        'leave_request': [
            ('rejection_reason', 'TEXT'),
            ('parent_status', 'VARCHAR(50)'),
            ('parent_rejection_reason', 'TEXT'),
            ('teacher_status', 'VARCHAR(50)'),
            ('teacher_rejection_reason', 'TEXT'),
            ('forwarded_to_warden', 'BOOLEAN'),
            ('warden_status', 'VARCHAR(50)'),
            ('warden_rejection_reason', 'TEXT'),
        ],
        'room_issue': [
            ('admin_note', 'TEXT'),
            ('issue_type', 'VARCHAR(50)'),
            ('forwarded_to', 'VARCHAR(50)'),
            ('forwarded_at', 'DATETIME'),
            ('solved_at', 'DATETIME'),
            ('rating', 'INTEGER'),
            ('rating_comment', 'TEXT'),
            ('solution_note', 'TEXT'),
        ],
    }

    for table_name, additions in table_migrations.items():
        if table_name not in inspector.get_table_names():
            continue
        columns = {col['name'] for col in inspector.get_columns(table_name)}
        for col_name, col_type in additions:
            if col_name not in columns:
                db.session.execute(text(f'ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}'))
    db.session.commit()


with app.app_context():
    db.create_all()
    migrate_db_columns()

    if not Admin.query.first():
        admin = Admin(
            username="warden",
            password="1234",
            role="warden",
            security_question_1="What is your favorite food?",
            security_answer_1="pizza",
            security_question_2="What is your favorite place?",
            security_answer_2="beach"
        )
        db.session.add(admin)
        db.session.commit()

    for existing_admin in Admin.query.filter((Admin.role == None) | (Admin.role == '')).all():
        existing_admin.role = 'warden'

    for leave_req in LeaveRequest.query.filter((LeaveRequest.teacher_status == None) | (LeaveRequest.teacher_status == '')).all():
        leave_req.teacher_status = 'Pending'
        if leave_req.status == 'Approved':
            leave_req.teacher_status = 'Approved'
            leave_req.forwarded_to_warden = True
            leave_req.warden_status = 'Approved'
        elif leave_req.status == 'Not Approved':
            leave_req.teacher_status = 'Not Approved'
            leave_req.teacher_rejection_reason = leave_req.rejection_reason or ''

    for issue in RoomIssue.query.filter((RoomIssue.issue_type == None) | (RoomIssue.issue_type == '')).all():
        issue.issue_type = 'General Maintenance'

    db.session.commit()


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_upload(file, folder, prefix):
    if file and file.filename and allowed_file(file.filename):
        filename = secure_filename(f"{prefix}_{datetime.now().timestamp()}_{file.filename}")
        file.save(os.path.join(folder, filename))
        return filename
    return None


def get_logged_in_student():
    if 'student_id' not in session:
        return None
    return Student.query.get(session['student_id'])


def get_logged_in_admin():
    if 'admin_id' not in session:
        return None
    return Admin.query.get(session['admin_id'])


def require_admin_role(*roles):
    admin = get_logged_in_admin()
    if not admin:
        return None, redirect('/login')
    if roles and admin.role not in roles:
        return None, render_template(
            'access_denied.html',
            admin=admin,
            roles=AUTHORITY_ROLES,
            required_roles=[AUTHORITY_ROLES.get(r, r) for r in roles]
        )
    return admin, None


def issue_type_to_worker(issue_type):
    return ISSUE_TYPES.get(issue_type, 'general')


def delete_student_account(student):
    for leave_req in LeaveRequest.query.filter_by(student_id=student.id).all():
        if leave_req.approval_image:
            image_path = os.path.join(app.config['LEAVE_UPLOAD_FOLDER'], leave_req.approval_image)
            if os.path.exists(image_path):
                os.remove(image_path)
        db.session.delete(leave_req)

    for issue in RoomIssue.query.filter_by(student_id=student.id).all():
        if issue.image_filename:
            image_path = os.path.join(app.config['ROOM_ISSUE_UPLOAD_FOLDER'], issue.image_filename)
            if os.path.exists(image_path):
                os.remove(image_path)
        db.session.delete(issue)

    for complaint in Complaint.query.filter_by(student_id=student.id).all():
        if complaint.image_filename:
            image_path = os.path.join(app.config['COMPLAINT_UPLOAD_FOLDER'], complaint.image_filename)
            if os.path.exists(image_path):
                os.remove(image_path)
        db.session.delete(complaint)

    db.session.delete(student)


@app.route('/')
def home():
    return render_template("index.html")


@app.route('/timetable')
def timetable():
    menu = Menu.query.order_by(Menu.sort_order).all()
    return render_template("timetable.html", menu=menu)


@app.route('/login', methods=['GET','POST'])
def login():
    error = None
    
    if request.method == "POST":
        username = request.form['username']
        password = request.form['password']

        admin = Admin.query.filter_by(
            username=username,
            password=password
        ).first()

        if admin:
            session['admin'] = username
            session['admin_id'] = admin.id
            session['admin_role'] = admin.role or 'warden'
            return redirect('/authorities')
        else:
            error = "Invalid username or password"

    return render_template("login.html", error=error)


@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    success = None
    
    if request.method == "POST":
        username = request.form['username']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        email = request.form['email']
        security_q1 = request.form['security_q1']
        security_a1 = request.form['security_a1']
        security_q2 = request.form['security_q2']
        security_a2 = request.form['security_a2']
        role = request.form.get('role', 'warden').strip()

        if role not in AUTHORITY_ROLES:
            error = "Please select a valid role"
        elif Admin.query.filter_by(username=username).first():
            error = "Username already exists"
        elif password != confirm_password:
            error = "Passwords do not match"
        elif len(password) < 6:
            error = "Password must be at least 6 characters"
        else:
            admin = Admin(
                username=username,
                password=password,
                email=email,
                role=role,
                security_question_1=security_q1,
                security_answer_1=security_a1.lower(),
                security_question_2=security_q2,
                security_answer_2=security_a2.lower()
            )
            db.session.add(admin)
            db.session.commit()
            success = "Registration successful! Please login."
            return redirect('/login')

    return render_template("register.html", error=error, success=success)


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    error = None
    admin = None
    
    if request.method == "POST":
        username = request.form['username']
        admin = Admin.query.filter_by(username=username).first()

        if not admin:
            error = "Username not found"
        else:
            session['reset_username'] = username
            return redirect('/security-questions')

    return render_template("forgot_password.html", error=error)


@app.route('/security-questions', methods=['GET', 'POST'])
def security_questions():
    error = None
    
    if 'reset_username' not in session:
        return redirect('/forgot-password')
    
    admin = Admin.query.filter_by(username=session['reset_username']).first()
    
    if request.method == "POST":
        answer_1 = request.form['answer_1'].lower()
        answer_2 = request.form['answer_2'].lower()

        if (answer_1 == admin.security_answer_1 and 
            answer_2 == admin.security_answer_2):
            session['verified_user'] = admin.id
            return redirect('/reset-password')
        else:
            error = "Incorrect answers to security questions"

    return render_template("security_questions.html", 
                         admin=admin, 
                         error=error)


@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    error = None
    success = None
    
    if 'verified_user' not in session:
        return redirect('/forgot-password')
    
    admin = Admin.query.get(session['verified_user'])
    
    if request.method == "POST":
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']

        if new_password != confirm_password:
            error = "Passwords do not match"
        elif len(new_password) < 6:
            error = "Password must be at least 6 characters"
        else:
            admin.password = new_password
            db.session.commit()
            success = "Password reset successful! Please login."
            session.pop('reset_username', None)
            session.pop('verified_user', None)
            return redirect('/login')

    return render_template("reset_password.html", error=error, success=success)


@app.route('/authorities')
def authorities_hub():
    admin, resp = require_admin_role()
    if resp:
        return resp

    return render_template(
        'authorities_hub.html',
        admin=admin,
        roles=AUTHORITY_ROLES
    )


@app.route('/dashboard')
def dashboard():
    admin, resp = require_admin_role('warden')
    if resp:
        return resp

    menu = Menu.query.order_by(Menu.sort_order).all()

    return render_template(
        'admin_dashboard.html',
        menu=menu,
        admin=admin
    )


@app.route('/portal/class-incharge')
def portal_class_incharge():
    admin, resp = require_admin_role('class_incharge')
    if resp:
        return resp

    leave_requests = (
        LeaveRequest.query
        .join(Student, LeaveRequest.student_id == Student.id)
        .filter(LeaveRequest.parent_status == 'Approved')
        .filter(Student.class_incharge_email == admin.email)
        .filter(db.or_(LeaveRequest.teacher_status == 'Pending', LeaveRequest.teacher_status == None, LeaveRequest.teacher_status == ''))
        .order_by(LeaveRequest.submitted_at.desc())
        .all()
    )

    return render_template(
        'portal_class_incharge.html',
        admin=admin,
        leave_requests=leave_requests
    )


@app.route('/portal/warden')
def portal_warden():
    admin, resp = require_admin_role('warden')
    if resp:
        return resp

    forwarded_leaves = (
        LeaveRequest.query
        .join(Student, LeaveRequest.student_id == Student.id)
        .filter(LeaveRequest.forwarded_to_warden == True)
        .order_by(LeaveRequest.submitted_at.desc())
        .all()
    )

    all_feedbacks = []
    
    room_issues = RoomIssue.query.join(Student, RoomIssue.student_id == Student.id, isouter=True).all()
    for i in room_issues:
        all_feedbacks.append({
            'type': 'room_issue',
            'db_id': i.id,
            'category': i.issue_type,
            'day': '',
            'date': i.issue_date.strftime('%d %b %Y') if i.issue_date else '',
            'time': i.issue_time,
            'message': i.message,
            'image_filename': i.image_filename,
            'status': i.status,
            'submitted_at': i.submitted_at,
            'student_name': i.student.name if i.student else 'Anonymous',
            'room_number': i.room_number or (i.student.room_number if i.student else 'N/A'),
            'rating': i.rating,
            'rating_comment': i.rating_comment,
            'forwarded_to': i.forwarded_to
        })

    food_complaints = Complaint.query.join(Student, Complaint.student_id == Student.id, isouter=True).all()
    for c in food_complaints:
        all_feedbacks.append({
            'type': 'complaint',
            'db_id': c.id,
            'category': 'Cook',
            'day': c.day,
            'date': c.feedback_date.strftime('%d %b %Y') if c.feedback_date else '',
            'time': c.feedback_time,
            'message': c.message,
            'image_filename': c.image_filename,
            'status': c.status,
            'submitted_at': c.submitted_at,
            'student_name': c.student_name or 'Anonymous',
            'room_number': c.student.room_number if (c.student and c.student.room_number) else 'N/A',
            'rating': c.rating,
            'rating_comment': c.rating_comment,
            'forwarded_to': 'chief' if c.forwarded_to_chief else None
        })
        
    all_feedbacks.sort(key=lambda x: x['submitted_at'], reverse=True)

    return render_template(
        'portal_warden.html',
        admin=admin,
        forwarded_leaves=forwarded_leaves,
        all_feedbacks=all_feedbacks,
        issue_types=ISSUE_TYPES
    )


@app.route('/portal/carpenter')
def portal_carpenter():
    admin, resp = require_admin_role('carpenter')
    if resp:
        return resp

    issues = (
        RoomIssue.query
        .join(Student, RoomIssue.student_id == Student.id)
        .filter(RoomIssue.forwarded_to == 'carpenter')
        .order_by(RoomIssue.submitted_at.desc())
        .all()
    )

    return render_template('portal_worker.html', admin=admin, issues=issues, worker_role='carpenter')


@app.route('/portal/electrician')
def portal_electrician():
    admin, resp = require_admin_role('electrician')
    if resp:
        return resp

    issues = (
        RoomIssue.query
        .join(Student, RoomIssue.student_id == Student.id)
        .filter(RoomIssue.forwarded_to == 'electrician')
        .order_by(RoomIssue.submitted_at.desc())
        .all()
    )

    return render_template('portal_worker.html', admin=admin, issues=issues, worker_role='electrician')


@app.route('/portal/plumber')
def portal_plumber():
    admin, resp = require_admin_role('plumber')
    if resp:
        return resp

    issues = (
        RoomIssue.query
        .join(Student, RoomIssue.student_id == Student.id)
        .filter(RoomIssue.forwarded_to == 'plumber')
        .order_by(RoomIssue.submitted_at.desc())
        .all()
    )

    return render_template('portal_worker.html', admin=admin, issues=issues, worker_role='plumber')


@app.route('/portal/chief')
def portal_chief():
    admin, resp = require_admin_role('chief')
    if resp:
        return resp

    complaints = (
        Complaint.query
        .join(Student, Complaint.student_id == Student.id)
        .filter(Complaint.forwarded_to_chief == True)
        .order_by(Complaint.submitted_at.desc())
        .all()
    )

    return render_template('portal_chief.html', admin=admin, complaints=complaints)


@app.route('/portal/dean')
def portal_dean():
    admin, resp = require_admin_role('dean')
    if resp:
        return resp

    leave_requests = (
        LeaveRequest.query
        .join(Student, LeaveRequest.student_id == Student.id)
        .order_by(LeaveRequest.submitted_at.desc())
        .all()
    )

    room_issues = (
        RoomIssue.query
        .join(Student, RoomIssue.student_id == Student.id)
        .order_by(RoomIssue.submitted_at.desc())
        .all()
    )

    food_complaints = (
        Complaint.query
        .join(Student, Complaint.student_id == Student.id)
        .order_by(Complaint.submitted_at.desc())
        .all()
    )

    students = Student.query.all()
    today = date.today()
    attendance_records = Attendance.query.filter_by(date=today).all()
    present_count = sum(1 for a in attendance_records if a.status == 'Present')
    absent_count = sum(1 for a in attendance_records if a.status == 'Absent')
    leave_att_count = sum(1 for a in attendance_records if a.status == 'Leave')

    carpenter_issues = [i for i in room_issues if i.forwarded_to == 'carpenter']
    electrician_issues = [i for i in room_issues if i.forwarded_to == 'electrician']
    plumber_issues = [i for i in room_issues if i.forwarded_to == 'plumber']
    chief_complaints = [c for c in food_complaints if c.forwarded_to_chief]

    # Build monthly chart data for current month
    import calendar
    current_month = today.month
    current_year = today.year
    days_in_month = calendar.monthrange(current_year, current_month)[1]
    day_labels = [str(d) for d in range(1, days_in_month + 1)]

    def count_by_day(items, date_attr='submitted_at'):
        counts = [0] * days_in_month
        for item in items:
            d = getattr(item, date_attr)
            if d and d.year == current_year and d.month == current_month:
                counts[d.day - 1] += 1
        return counts

    def count_solved_by_day(items):
        counts = [0] * days_in_month
        for item in items:
            if item.solved_at and item.solved_at.year == current_year and item.solved_at.month == current_month:
                counts[item.solved_at.day - 1] += 1
        return counts

    chart_data = {
        'labels': day_labels,
        'carpenter_complaints': count_by_day(carpenter_issues),
        'carpenter_solved': count_solved_by_day(carpenter_issues),
        'electrician_complaints': count_by_day(electrician_issues),
        'electrician_solved': count_solved_by_day(electrician_issues),
        'plumber_complaints': count_by_day(plumber_issues),
        'plumber_solved': count_solved_by_day(plumber_issues),
        'chief_complaints': count_by_day(chief_complaints),
        'chief_solved': count_solved_by_day(chief_complaints),
        'leave_requests': count_by_day(leave_requests),
    }

    import json
    chart_data_json = json.dumps(chart_data)

    return render_template(
        'portal_dean.html',
        admin=admin,
        leave_requests=leave_requests,
        room_issues=room_issues,
        food_complaints=food_complaints,
        carpenter_issues=carpenter_issues,
        electrician_issues=electrician_issues,
        plumber_issues=plumber_issues,
        chief_complaints=chief_complaints,
        students=students,
        present_count=present_count,
        absent_count=absent_count,
        leave_att_count=leave_att_count,
        today=today,
        chart_data_json=chart_data_json
    )


@app.route('/add_menu', methods=['POST'])
def add_menu():
    if 'admin' not in session:
        return redirect('/login')

    day = request.form['day']
    breakfast = request.form['breakfast']
    lunch = request.form['lunch']
    dinner = request.form['dinner']
    snacks = request.form.get('snacks', '')
    
    image_filename = None
    
    # Handle file upload
    if 'image' in request.files:
        file = request.files['image']
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(f"{day}_{datetime.now().timestamp()}_{file.filename}")
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            image_filename = filename

    # Get the highest sort_order and add 1
    max_sort = db.session.query(db.func.max(Menu.sort_order)).scalar() or 0
    sort_order = max_sort + 1

    m = Menu(
        day=day,
        breakfast=breakfast,
        lunch=lunch,
        dinner=dinner,
        snacks=snacks,
        image_filename=image_filename,
        sort_order=sort_order
    )

    db.session.add(m)
    db.session.commit()

    return redirect('/dashboard')

@app.route('/edit_menu/<int:id>', methods=['POST'])
def edit_menu(id):
    if 'admin' not in session:
        return redirect('/login')

    menu = Menu.query.get_or_404(id)
    menu.day = request.form['day']
    menu.breakfast = request.form['breakfast']
    menu.lunch = request.form['lunch']
    menu.dinner = request.form['dinner']
    menu.snacks = request.form.get('snacks', '')

    if 'image' in request.files:
        file = request.files['image']
        if file and file.filename and allowed_file(file.filename):
            # Optionally remove old image
            if menu.image_filename:
                old_path = os.path.join(app.config['UPLOAD_FOLDER'], menu.image_filename)
                if os.path.exists(old_path):
                    try:
                        os.remove(old_path)
                    except:
                        pass
            filename = secure_filename(f"{menu.day}_{datetime.now().timestamp()}_{file.filename}")
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            menu.image_filename = filename

    db.session.commit()
    return redirect('/dashboard')


@app.route('/delete/<int:id>')
def delete(id):
    if 'admin' not in session:
        return redirect('/login')

    menu = Menu.query.get(id)
    
    # Delete associated image if exists
    if menu.image_filename:
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], menu.image_filename)
        if os.path.exists(image_path):
            os.remove(image_path)

    db.session.delete(menu)
    db.session.commit()

    return redirect('/dashboard')


@app.route('/complaints')
def complaints():
    if 'admin' not in session:
        return redirect('/login')

    all_feedbacks = []
    room_issues = RoomIssue.query.join(Student, RoomIssue.student_id == Student.id, isouter=True).all()
    for i in room_issues:
        all_feedbacks.append({
            'type': 'room_issue',
            'db_id': i.id,
            'category': i.issue_type,
            'day': '',
            'date': i.issue_date.strftime('%d %b %Y') if i.issue_date else '',
            'time': i.issue_time,
            'message': i.message,
            'image_filename': i.image_filename,
            'status': i.status,
            'submitted_at': i.submitted_at,
            'student_name': i.student.name if i.student else 'Anonymous',
            'room_number': i.room_number or (i.student.room_number if i.student else 'N/A'),
            'rating': i.rating,
            'rating_comment': i.rating_comment,
            'forwarded_to': i.forwarded_to
        })

    food_complaints = Complaint.query.join(Student, Complaint.student_id == Student.id, isouter=True).all()
    for c in food_complaints:
        all_feedbacks.append({
            'type': 'complaint',
            'db_id': c.id,
            'category': 'Cook',
            'day': c.day,
            'date': c.feedback_date.strftime('%d %b %Y') if c.feedback_date else '',
            'time': c.feedback_time,
            'message': c.message,
            'image_filename': c.image_filename,
            'status': c.status,
            'submitted_at': c.submitted_at,
            'student_name': c.student_name or 'Anonymous',
            'room_number': c.student.room_number if (c.student and c.student.room_number) else 'N/A',
            'rating': c.rating,
            'rating_comment': c.rating_comment,
            'forwarded_to': 'chief' if c.forwarded_to_chief else None
        })
        
    all_feedbacks.sort(key=lambda x: x['submitted_at'], reverse=True)

    return render_template(
        'complaints.html',
        complaints=all_feedbacks
    )


@app.route('/rearrange', methods=['GET', 'POST'])
def rearrange():
    if 'admin' not in session:
        return redirect('/login')
    
    menu = Menu.query.order_by(Menu.sort_order).all()
    
    if request.method == 'POST':
        # Get the new order from form
        days_order = request.form.getlist('day_order')
        
        for index, day_id in enumerate(days_order):
            try:
                menu_item = Menu.query.get(int(day_id))
                if menu_item:
                    menu_item.sort_order = index
            except:
                pass
        
        db.session.commit()
        return redirect('/dashboard')
    
    return render_template('rearrange_menu.html', menu=menu)

@app.route('/logout')
def logout():
    session.pop('admin', None)
    session.pop('admin_id', None)
    session.pop('admin_role', None)
    session.pop('student_id', None)
    session.pop('student_name', None)
    session.pop('student_reset_username', None)
    session.pop('student_verified_user', None)

    return redirect('/')



def get_logged_in_parent():
    if 'parent_id' not in session:
        return None
    return Parent.query.get(session['parent_id'])

@app.route('/parent/login', methods=['GET', 'POST'])
def parent_login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        parent = Parent.query.filter_by(username=username, password=password).first()
        if parent:
            session['parent_id'] = parent.id
            session['parent_name'] = parent.name
            return redirect('/parent/dashboard')
        error = "Invalid username or password"
    return render_template('parent_login.html', error=error)

@app.route('/parent/register', methods=['GET', 'POST'])
def parent_register():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        student_name = request.form.get('student_name', '').strip()
        student_email = request.form.get('student_email', '').strip()
        phone_number = request.form.get('phone_number', '').strip()
        security_q1 = request.form.get('security_q1', '').strip()
        security_a1 = request.form.get('security_a1', '').strip()
        security_q2 = request.form.get('security_q2', '').strip()
        security_a2 = request.form.get('security_a2', '').strip()

        if Parent.query.filter_by(username=username).first():
            error = "Username already exists."
        elif Parent.query.filter_by(email=email).first():
            error = "Email already registered."
        elif password != confirm_password:
            error = "Passwords do not match."
        elif not all([username, password, name, email, student_name, student_email, security_q1, security_a1, security_q2, security_a2]):
            error = "Please fill out all required fields."
        else:
            new_parent = Parent(
                username=username,
                password=password,
                name=name,
                email=email,
                student_name=student_name,
                student_email=student_email,
                phone_number=phone_number,
                security_question_1=security_q1,
                security_answer_1=security_a1,
                security_question_2=security_q2,
                security_answer_2=security_a2
            )
            db.session.add(new_parent)
            db.session.commit()
            return redirect('/parent/login')
    return render_template('parent_register.html', error=error)

@app.route('/parent/dashboard')
def parent_dashboard():
    parent = get_logged_in_parent()
    if not parent:
        return redirect('/parent/login')

    student = Student.query.filter_by(email=parent.student_email, name=parent.student_name).first()
    leaves = []
    if student:
        leaves = LeaveRequest.query.filter_by(student_id=student.id).order_by(LeaveRequest.submitted_at.desc()).all()
    notifications = []
    if student and student.parent_email:
        notifications = Notification.query.filter(
            db.or_(Notification.parent_email == parent.email, Notification.parent_email == student.parent_email)
        ).order_by(Notification.created_at.desc()).all()
    else:
        notifications = Notification.query.filter_by(parent_email=parent.email).order_by(Notification.created_at.desc()).all()
    return render_template('parent_dashboard.html', parent=parent, student=student, leaves=leaves, notifications=notifications)

@app.route('/parent/leave/update', methods=['POST'])
def parent_update_leave():
    parent = get_logged_in_parent()
    if not parent:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    data = request.get_json()
    leave_id = data.get('leave_id')
    status = data.get('status')
    reason = data.get('reason', '').strip()

    if status not in ('Approved', 'Not Approved'):
        return jsonify({'success': False, 'error': 'Invalid status'}), 400

    leave = LeaveRequest.query.get(leave_id)
    if not leave:
        return jsonify({'success': False, 'error': 'Leave request not found'}), 404

    leave.parent_status = status
    if status == 'Not Approved':
        leave.parent_rejection_reason = reason
        leave.status = 'Not Approved'
    db.session.commit()

    return jsonify({'success': True})

@app.route('/parent/notifications/read', methods=['POST'])
def parent_mark_notifications_read():
    parent = get_logged_in_parent()
    if not parent:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    student = Student.query.filter_by(email=parent.student_email, name=parent.student_name).first()
    emails = [parent.email]
    if student and student.parent_email:
        emails.append(student.parent_email)
        
    Notification.query.filter(Notification.parent_email.in_(emails), Notification.is_read == False).update({'is_read': True})
    db.session.commit()
    return jsonify({'success': True})

@app.route('/parent/logout')
def parent_logout():
    session.pop('parent_id', None)
    session.pop('parent_name', None)
    return redirect('/student_parent_hub')

@app.route('/student_parent_hub')
def student_parent_hub():
    return render_template('student_parent_hub.html')


@app.route('/student/login', methods=['GET', 'POST'])
def student_login():
    error = None

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        student = Student.query.filter_by(username=username, password=password).first()

        if student:
            session['student_id'] = student.id
            session['student_name'] = student.name
            return redirect('/student/dashboard')
        error = "Invalid username or password"

    return render_template('student_login.html', error=error)


@app.route('/student/register', methods=['GET', 'POST'])
def student_register():
    error = None

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        name = request.form.get('name', '').strip()
        student_class = request.form.get('student_class', '').strip()
        phone_number = request.form.get('phone_number', '').strip()
        parent_phone = request.form.get('parent_phone', '').strip()
        parent_email = request.form.get('parent_email', '').strip()
        class_incharge_email = request.form.get('class_incharge_email', '').strip()
        room_number = request.form.get('room_number', '').strip()
        email = request.form.get('email', '').strip()
        security_q1 = request.form.get('security_q1', '').strip()
        security_a1 = request.form.get('security_a1', '').strip()
        security_q2 = request.form.get('security_q2', '').strip()
        security_a2 = request.form.get('security_a2', '').strip()

        if Student.query.filter_by(username=username).first():
            error = "Username already exists"
        elif Student.query.filter_by(phone_number=phone_number).first():
            error = "Phone number already registered"
        elif password != confirm_password:
            error = "Passwords do not match"
        elif len(password) < 6:
            error = "Password must be at least 6 characters"
        elif not name or not student_class or not phone_number or not parent_phone:
            error = "Please fill in all required profile fields"
        elif not parent_email or not class_incharge_email:
            error = "Parent email and class incharge email are required"
        else:
            student = Student(
                username=username,
                password=password,
                name=name,
                student_class=student_class,
                phone_number=phone_number,
                parent_phone=parent_phone,
                parent_email=parent_email,
                class_incharge_email=class_incharge_email,
                room_number=room_number,
                email=email,
                security_question_1=security_q1,
                security_answer_1=security_a1.lower(),
                security_question_2=security_q2,
                security_answer_2=security_a2.lower()
            )
            db.session.add(student)
            db.session.commit()
            return redirect('/student/login')

    return render_template('student_register.html', error=error)


@app.route('/student/forgot-password', methods=['GET', 'POST'])
def student_forgot_password():
    error = None

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        student = Student.query.filter_by(username=username).first()

        if not student:
            error = "Username not found"
        else:
            session['student_reset_username'] = username
            return redirect('/student/security-questions')

    return render_template('student_forgot_password.html', error=error)


@app.route('/student/security-questions', methods=['GET', 'POST'])
def student_security_questions():
    error = None

    if 'student_reset_username' not in session:
        return redirect('/student/forgot-password')

    student = Student.query.filter_by(username=session['student_reset_username']).first()

    if request.method == 'POST':
        answer_1 = request.form.get('answer_1', '').lower()
        answer_2 = request.form.get('answer_2', '').lower()

        if (answer_1 == student.security_answer_1 and
                answer_2 == student.security_answer_2):
            session['student_verified_user'] = student.id
            return redirect('/student/reset-password')
        error = "Incorrect answers to security questions"

    return render_template('student_security_questions.html', student=student, error=error)


@app.route('/student/reset-password', methods=['GET', 'POST'])
def student_reset_password():
    error = None

    if 'student_verified_user' not in session:
        return redirect('/student/forgot-password')

    student = Student.query.get(session['student_verified_user'])

    if request.method == 'POST':
        new_password = request.form.get('new_password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()

        if new_password != confirm_password:
            error = "Passwords do not match"
        elif len(new_password) < 6:
            error = "Password must be at least 6 characters"
        else:
            student.password = new_password
            db.session.commit()
            session.pop('student_reset_username', None)
            session.pop('student_verified_user', None)
            return redirect('/student/login')

    return render_template('student_reset_password.html', error=error)


@app.route('/student/dashboard')
def student_dashboard():
    student = get_logged_in_student()
    if not student:
        return redirect('/student/login')

    leave_requests = LeaveRequest.query.filter_by(student_id=student.id).order_by(LeaveRequest.submitted_at.desc()).all()
    room_issues = RoomIssue.query.filter_by(student_id=student.id).order_by(RoomIssue.submitted_at.desc()).all()
    food_complaints = Complaint.query.filter_by(student_id=student.id).order_by(Complaint.submitted_at.desc()).all()
    today = date.today()
    today_attendance = Attendance.query.filter_by(student_id=student.id, date=today).first()
    attendance_history = (
        Attendance.query
        .filter_by(student_id=student.id)
        .order_by(Attendance.date.desc())
        .limit(30)
        .all()
    )

    return render_template(
        'student_dashboard.html',
        student=student,
        leave_requests=leave_requests,
        room_issues=room_issues,
        food_complaints=food_complaints,
        leave_count=len(leave_requests),
        issue_count=len(room_issues),
        today_attendance=today_attendance,
        attendance_history=attendance_history,
        today=today
    )


@app.route('/student/leave', methods=['GET', 'POST'])
def student_leave():
    student = get_logged_in_student()
    if not student:
        return redirect('/student/login')

    error = None
    success = None

    if request.method == 'POST':
        leave_message = request.form.get('leave_message', '').strip()
        from_date_str = request.form.get('from_date', '').strip()
        to_date_str = request.form.get('to_date', '').strip()

        if not leave_message or len(leave_message) < 10:
            error = "Please write your leave message (minimum 10 characters)."
        else:
            from_date = None
            to_date = None
            try:
                if from_date_str:
                    from_date = datetime.strptime(from_date_str, '%Y-%m-%d').date()
                if to_date_str:
                    to_date = datetime.strptime(to_date_str, '%Y-%m-%d').date()
            except ValueError:
                error = "Invalid date format."

            if not error:
                leave_req = LeaveRequest(
                    student_id=student.id,
                    leave_message=leave_message,
                    from_date=from_date,
                    to_date=to_date,
                    parent_status='Pending',
                    teacher_status='Pending',
                    warden_status='Pending',
                    status='Pending',
                    submitted_at=datetime.now()
                )
                db.session.add(leave_req)
                db.session.commit()
                success = "Leave request submitted successfully!"
                return redirect('/student/dashboard')

    today = date.today()
    return render_template('student_leave.html', student=student, error=error, success=success, today=today)


@app.route('/student/room-issue', methods=['GET', 'POST'])
def student_room_issue():
    student = get_logged_in_student()
    if not student:
        return redirect('/student/login')

    error = None
    success = None
    today = date.today()
    current_time = datetime.now().strftime('%H:%M')

    if request.method == 'POST':
        message = request.form.get('message', '').strip()
        issue_type = request.form.get('issue_type', 'General Maintenance').strip()
        issue_date_str = request.form.get('issue_date', '').strip()
        issue_time = request.form.get('issue_time', '').strip()

        if issue_type not in ISSUE_TYPES:
            error = "Please select a valid issue type."
        elif not message or len(message) < 10:
            error = "Please describe the room issue (minimum 10 characters)."
        elif 'image' not in request.files or not request.files['image'].filename:
            error = "Please upload a photo of the problem."
        else:
            issue_date = date.today()
            if issue_date_str:
                try:
                    issue_date = datetime.strptime(issue_date_str, '%Y-%m-%d').date()
                except ValueError:
                    error = "Invalid date format."

            if not error:
                image_filename = save_upload(
                    request.files['image'],
                    app.config['ROOM_ISSUE_UPLOAD_FOLDER'],
                    f"room_{student.id}"
                )
                if not image_filename:
                    error = "Invalid image file. Use PNG, JPG, JPEG or GIF."
                else:
                    issue = RoomIssue(
                        student_id=student.id,
                        room_number=student.room_number or '',
                        issue_type=issue_type,
                        issue_date=issue_date,
                        issue_time=issue_time,
                        message=message,
                        image_filename=image_filename,
                        submitted_at=datetime.now()
                    )
                    db.session.add(issue)
                    db.session.commit()
                    success = "Room issue reported successfully!"
                    return redirect('/student/dashboard')

    return render_template(
        'student_room_issue.html',
        student=student,
        error=error,
        success=success,
        today=today,
        current_time=current_time,
        issue_types=list(ISSUE_TYPES.keys())
    )


@app.route('/student/food-complaint', methods=['GET', 'POST'])
def student_food_complaint():
    student = get_logged_in_student()
    if not student:
        return redirect('/student/login')

    error = None
    today = date.today()
    current_time = datetime.now().strftime('%H:%M')
    current_day = today.strftime('%A')
    weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    menu_days = [item.day for item in Menu.query.all() if item.day]
    day_options = menu_days if menu_days else weekdays

    if request.method == 'POST':
        msg = request.form.get('message', '').strip()
        day = request.form.get('day', '').strip()
        feedback_date_str = request.form.get('feedback_date', '').strip()
        feedback_time = request.form.get('feedback_time', '').strip()

        feedback_date = date.today()
        if feedback_date_str:
            try:
                feedback_date = datetime.strptime(feedback_date_str, '%Y-%m-%d').date()
            except ValueError:
                error = "Invalid date format."

        image_filename = None
        if 'image' in request.files:
            image_filename = save_upload(
                request.files['image'],
                app.config['COMPLAINT_UPLOAD_FOLDER'],
                f"food_{student.id}"
            )

        if not error:
            if not msg or len(msg) < 10:
                error = "Please write your feedback (minimum 10 characters)."
            else:
                c = Complaint(
                    student_id=student.id,
                    student_name=student.name,
                    day=day,
                    feedback_date=feedback_date,
                    feedback_time=feedback_time,
                    message=msg,
                    image_filename=image_filename,
                    submitted_at=datetime.now(),
                    status='Pending'
                )
                db.session.add(c)
                db.session.commit()
                return redirect('/student/dashboard')

    return render_template(
        'student_food_complaint.html',
        student=student,
        error=error,
        today=today,
        current_time=current_time,
        current_day=current_day,
        day_options=day_options
    )


@app.route('/leave-requests/teacher-update', methods=['POST'])
def update_teacher_leave_status():
    admin, resp = require_admin_role('class_incharge')
    if resp:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    data = request.get_json()
    req_id = data.get('request_id')
    status = data.get('status')
    reason = data.get('reason', '').strip()

    if status not in ('Approved', 'Not Approved'):
        return jsonify({'success': False, 'error': 'Invalid status'}), 400

    leave_req = LeaveRequest.query.get(req_id)
    if not leave_req:
        return jsonify({'success': False, 'error': 'Request not found'}), 404

    if status == 'Not Approved' and not reason:
        return jsonify({'success': False, 'error': 'Reason required for rejection'}), 400

    leave_req.teacher_status = status
    leave_req.teacher_rejection_reason = reason if status == 'Not Approved' else ''
    if status == 'Not Approved':
        leave_req.status = 'Not Approved'
        leave_req.rejection_reason = reason
    db.session.commit()

    return jsonify({'success': True, 'teacher_status': status})


@app.route('/leave-requests/forward-warden', methods=['POST'])
def forward_leave_to_warden():
    admin, resp = require_admin_role('class_incharge')
    if resp:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    data = request.get_json()
    req_id = data.get('request_id')
    leave_req = LeaveRequest.query.get(req_id)

    if not leave_req:
        return jsonify({'success': False, 'error': 'Request not found'}), 404

    if leave_req.teacher_status != 'Approved':
        return jsonify({'success': False, 'error': 'Leave must be approved by class incharge first'}), 400

    leave_req.forwarded_to_warden = True
    leave_req.warden_status = 'Pending'
    db.session.commit()

    return jsonify({'success': True})


@app.route('/leave-requests/warden-update', methods=['POST'])
def update_warden_leave_status():
    admin, resp = require_admin_role('warden')
    if resp:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    data = request.get_json()
    req_id = data.get('request_id')
    status = data.get('status')
    reason = data.get('reason', '').strip()

    if status not in ('Approved', 'Not Approved'):
        return jsonify({'success': False, 'error': 'Invalid status'}), 400

    leave_req = LeaveRequest.query.get(req_id)
    if not leave_req:
        return jsonify({'success': False, 'error': 'Request not found'}), 404

    if not leave_req.forwarded_to_warden:
        return jsonify({'success': False, 'error': 'Leave not forwarded to warden yet'}), 400

    if status == 'Not Approved' and not reason:
        return jsonify({'success': False, 'error': 'Reason required for rejection'}), 400

    leave_req.warden_status = status
    leave_req.warden_rejection_reason = reason if status == 'Not Approved' else ''
    leave_req.status = status
    leave_req.rejection_reason = reason if status == 'Not Approved' else ''
    db.session.commit()

    return jsonify({'success': True, 'warden_status': status, 'status': status})


@app.route('/leave-requests/update', methods=['POST'])
def update_leave_status():
    admin, resp = require_admin_role('warden')
    if resp:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    data = request.get_json()
    req_id = data.get('request_id')
    status = data.get('status')
    reason = data.get('reason', '').strip()

    if status not in ('Approved', 'Not Approved'):
        return jsonify({'success': False, 'error': 'Invalid status'}), 400

    leave_req = LeaveRequest.query.get(req_id)
    if not leave_req:
        return jsonify({'success': False, 'error': 'Request not found'}), 404

    if status == 'Not Approved' and not reason:
        return jsonify({'success': False, 'error': 'Reason required for rejection'}), 400

    leave_req.status = status
    leave_req.rejection_reason = reason if status == 'Not Approved' else ''
    db.session.commit()

    return jsonify({'success': True, 'status': status})


@app.route('/room-issues/forward', methods=['POST'])
def forward_room_issue():
    admin, resp = require_admin_role('warden')
    if resp:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    data = request.get_json()
    issue_id = data.get('issue_id')
    worker = data.get('worker', '').strip()

    valid_workers = set(ISSUE_TYPES.values())
    if worker not in valid_workers:
        return jsonify({'success': False, 'error': 'Invalid worker role'}), 400

    issue = RoomIssue.query.get(issue_id)
    if not issue:
        return jsonify({'success': False, 'error': 'Issue not found'}), 404

    issue.forwarded_to = worker
    issue.forwarded_at = datetime.now()
    issue.status = 'Planning'
    db.session.commit()

    return jsonify({'success': True, 'forwarded_to': worker})


@app.route('/complaints/forward-chief', methods=['POST'])
def forward_complaint_to_chief():
    admin, resp = require_admin_role('warden')
    if resp:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    data = request.get_json()
    complaint_id = data.get('complaint_id')

    complaint = Complaint.query.get(complaint_id)
    if not complaint:
        return jsonify({'success': False, 'error': 'Complaint not found'}), 404

    complaint.forwarded_to_chief = True
    complaint.forwarded_at = datetime.now()
    complaint.status = 'Planning'
    db.session.commit()

    return jsonify({'success': True})


@app.route('/room-issues/update', methods=['POST'])
def update_room_issue_status():
    admin = get_logged_in_admin()
    if not admin:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    data = request.get_json()
    issue_id = data.get('issue_id')
    status = data.get('status')
    solution_note = data.get('solution_note', '').strip()

    if status not in ('Pending', 'Solved', 'Planning'):
        return jsonify({'success': False, 'error': 'Invalid status'}), 400

    issue = RoomIssue.query.get(issue_id)
    if not issue:
        return jsonify({'success': False, 'error': 'Issue not found'}), 404

    if admin.role in ('carpenter', 'electrician', 'plumber'):
        if issue.forwarded_to != admin.role:
            return jsonify({'success': False, 'error': 'Not assigned to you'}), 403
    elif admin.role != 'warden':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    issue.status = status
    if status == 'Solved':
        issue.solved_at = datetime.now()
        if solution_note:
            issue.solution_note = solution_note
    db.session.commit()

    return jsonify({'success': True, 'status': status})


@app.route('/complaints/update', methods=['POST'])
def update_complaint_status():
    admin = get_logged_in_admin()
    if not admin:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    data = request.get_json()
    complaint_id = data.get('complaint_id')
    status = data.get('status')
    solution_note = data.get('solution_note', '').strip()

    if status not in ('Pending', 'Solved', 'Planning'):
        return jsonify({'success': False, 'error': 'Invalid status'}), 400

    complaint = Complaint.query.get(complaint_id)
    if not complaint:
        return jsonify({'success': False, 'error': 'Complaint not found'}), 404

    complaint.status = status
    if status == 'Solved':
        complaint.solved_at = datetime.now()
        if solution_note:
            complaint.solution_note = solution_note
    db.session.commit()

    return jsonify({'success': True, 'status': status})


@app.route('/complaints/delete/<int:id>')
def delete_complaint(id):
    if 'admin' not in session:
        return redirect('/login')

    complaint = Complaint.query.get(id)
    if complaint:
        if complaint.image_filename:
            image_path = os.path.join(app.config['COMPLAINT_UPLOAD_FOLDER'], complaint.image_filename)
            if os.path.exists(image_path):
                os.remove(image_path)
        db.session.delete(complaint)
        db.session.commit()

    return redirect('/complaints')

@app.route('/admin/feedback/delete', methods=['POST'])
def admin_delete_feedback():
    admin = get_logged_in_admin()
    if not admin:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    data = request.get_json()
    item_type = data.get('type')
    item_id = data.get('id')

    if item_type == 'room_issue':
        item = RoomIssue.query.get(item_id)
        folder = app.config['ROOM_ISSUE_UPLOAD_FOLDER']
    elif item_type == 'complaint':
        item = Complaint.query.get(item_id)
        folder = app.config['COMPLAINT_UPLOAD_FOLDER']
    else:
        return jsonify({'success': False, 'error': 'Invalid type'}), 400

    if not item:
        return jsonify({'success': False, 'error': 'Item not found'}), 404

    if item.image_filename:
        image_path = os.path.join(folder, item.image_filename)
        if os.path.exists(image_path):
            try:
                os.remove(image_path)
            except Exception:
                pass

    db.session.delete(item)
    db.session.commit()
    return jsonify({'success': True})


@app.route('/leave-requests/delete/<int:id>')
def delete_leave_request(id):
    if 'admin' not in session:
        return redirect('/login')

    leave_req = LeaveRequest.query.get(id)
    if leave_req:
        db.session.delete(leave_req)
        db.session.commit()

    return redirect('/leave-requests')


@app.route('/registered-students', methods=['GET', 'POST'])
def registered_students():
    if 'admin' not in session:
        return redirect('/login')

    error = None
    success = None

    if request.method == 'POST':
        student_id = request.form.get('student_id')
        student = Student.query.get(student_id)

        if not student:
            error = "Student not found."
        else:
            student.name = request.form.get('name', '').strip()
            student.phone_number = request.form.get('phone_number', '').strip()
            student.parent_phone = request.form.get('parent_phone', '').strip()
            student.parent_email = request.form.get('parent_email', '').strip()
            student.class_incharge_email = request.form.get('class_incharge_email', '').strip()
            student.email = request.form.get('email', '').strip()

            if not student.name or not student.phone_number or not student.parent_phone:
                error = "Name, phone and parent phone are required."
            else:
                db.session.commit()
                success = f"{student.name}'s details updated successfully!"

    students = Student.query.order_by(Student.name).all()
    return render_template(
        'admin_registered_students.html',
        students=students,
        error=error,
        success=success
    )


@app.route('/registered-students/delete/<int:id>')
def delete_registered_student(id):
    if 'admin' not in session:
        return redirect('/login')

    student = Student.query.get(id)
    if student:
        delete_student_account(student)
        db.session.commit()

    return redirect('/registered-students')


@app.route('/leave-requests')
def leave_requests():
    admin, resp = require_admin_role('warden')
    if resp:
        return resp

    requests = (
        LeaveRequest.query
        .join(Student, LeaveRequest.student_id == Student.id)
        .order_by(LeaveRequest.submitted_at.desc())
        .all()
    )

    return render_template('admin_leave_requests.html', leave_requests=requests, admin=admin)


@app.route('/room-issues')
def room_issues():
    admin, resp = require_admin_role('warden')
    if resp:
        return resp

    issues = (
        RoomIssue.query
        .join(Student, RoomIssue.student_id == Student.id)
        .order_by(RoomIssue.submitted_at.desc())
        .all()
    )

    return render_template(
        'admin_room_issues.html',
        room_issues=issues,
        admin=admin,
        issue_types=ISSUE_TYPES
    )


@app.route('/attendance')
def attendance():
    if 'admin' not in session:
        return redirect('/login')

    today = date.today()
    students = Student.query.order_by(Student.name).all()

    attendance_map = {}
    for record in Attendance.query.filter_by(date=today).all():
        attendance_map[record.student_id] = record.status

    present_count = sum(1 for status in attendance_map.values() if status == 'Present')
    absent_count = sum(1 for status in attendance_map.values() if status == 'Absent')
    leave_count = sum(1 for status in attendance_map.values() if status == 'Leave')
    unmarked_count = len(students) - len(attendance_map)

    return render_template(
        'attendance.html',
        students=students,
        attendance_map=attendance_map,
        today=today,
        present_count=present_count,
        absent_count=absent_count,
        leave_count=leave_count,
        unmarked_count=unmarked_count
    )


@app.route('/attendance/mark', methods=['POST'])
def mark_attendance():
    if 'admin' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    data = request.get_json()
    student_id = data.get('student_id')
    status = data.get('status')

    if status not in ('Present', 'Absent', 'Leave'):
        return jsonify({'success': False, 'error': 'Invalid status'}), 400

    student = Student.query.get(student_id)
    if not student:
        return jsonify({'success': False, 'error': 'Student not found'}), 404

    today = date.today()
    record = Attendance.query.filter_by(student_id=student_id, date=today).first()

    if record:
        record.status = status
        record.marked_at = datetime.now()
    else:
        record = Attendance(student_id=student_id, date=today, status=status)
        db.session.add(record)

    if status == 'Absent' and student.parent_email:
        notification = Notification(
            parent_email=student.parent_email,
            title="Absence Alert",
            message=f"{student.name} was marked absent on {today.strftime('%d %b %Y')}."
        )
        db.session.add(notification)

    db.session.commit()
    return jsonify({'success': True, 'status': status})


@app.route('/attendance/download')
def download_attendance():
    if 'admin' not in session:
        return redirect('/login')

    records = (
        db.session.query(Attendance, Student)
        .join(Student, Attendance.student_id == Student.id)
        .order_by(Attendance.date.desc(), Student.name)
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Student Name', 'Class', 'Phone', 'Parent Phone', 'Room', 'Status', 'Marked At'])

    for att, student in records:
        writer.writerow([
            att.date.strftime('%Y-%m-%d'),
            student.name,
            student.student_class,
            student.phone_number,
            student.parent_phone,
            student.room_number or '',
            att.status,
            att.marked_at.strftime('%Y-%m-%d %H:%M') if att.marked_at else ''
        ])

    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = (
        f'attachment; filename=attendance_{date.today().strftime("%Y%m%d")}.csv'
    )
    return response


@app.route('/attendance/clear', methods=['POST'])
def clear_attendance():
    if 'admin' not in session:
        return redirect('/login')

    Attendance.query.delete()
    db.session.commit()
    return redirect('/attendance')


@app.route('/room-issues/rate', methods=['POST'])
def rate_room_issue():
    student = get_logged_in_student()
    if not student:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    data = request.get_json()
    issue_id = data.get('issue_id')
    rating = data.get('rating')
    comment = data.get('comment', '').strip()

    if not rating or rating not in (1, 2, 3, 4, 5):
        return jsonify({'success': False, 'error': 'Invalid rating (1-5)'}), 400

    issue = RoomIssue.query.get(issue_id)
    if not issue:
        return jsonify({'success': False, 'error': 'Issue not found'}), 404
    if issue.student_id != student.id:
        return jsonify({'success': False, 'error': 'Not your issue'}), 403
    if issue.status != 'Solved':
        return jsonify({'success': False, 'error': 'Issue not solved yet'}), 400

    issue.rating = rating
    issue.rating_comment = comment
    db.session.commit()

    return jsonify({'success': True})


@app.route('/complaints/rate', methods=['POST'])
def rate_complaint():
    student = get_logged_in_student()
    if not student:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    data = request.get_json()
    complaint_id = data.get('complaint_id')
    rating = data.get('rating')
    comment = data.get('comment', '').strip()

    if not rating or rating not in (1, 2, 3, 4, 5):
        return jsonify({'success': False, 'error': 'Invalid rating (1-5)'}), 400

    complaint = Complaint.query.get(complaint_id)
    if not complaint:
        return jsonify({'success': False, 'error': 'Complaint not found'}), 404
    if complaint.student_id != student.id:
        return jsonify({'success': False, 'error': 'Not your complaint'}), 403
    if complaint.status != 'Solved':
        return jsonify({'success': False, 'error': 'Complaint not solved yet'}), 400

    complaint.rating = rating
    complaint.rating_comment = comment
    db.session.commit()

    return jsonify({'success': True})


if __name__ == "__main__":
    app.run(debug=True)