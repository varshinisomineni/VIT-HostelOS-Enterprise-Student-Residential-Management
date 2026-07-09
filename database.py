from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

AUTHORITY_ROLES = {
    'class_incharge': 'Class Incharge',
    'warden': 'Warden',
    'carpenter': 'Carpenter',
    'electrician': 'Electrician',
    'plumber': 'Plumber',
    'chief': 'Chief Cook',
    'dean': 'Dean',
}

ISSUE_TYPES = {
    'Carpenter Work': 'carpenter',
    'Electrician Work': 'electrician',
    'Plumbing Work': 'plumber',
}


class Menu(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    day = db.Column(db.String(50))
    breakfast = db.Column(db.String(200))
    lunch = db.Column(db.String(200))
    dinner = db.Column(db.String(200))
    snacks = db.Column(db.String(200), nullable=True, default="")
    image_filename = db.Column(db.String(200), nullable=True)
    sort_order = db.Column(db.Integer, default=0)


class Complaint(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=True)
    student_name = db.Column(db.String(100), nullable=True, default="Anonymous")
    day = db.Column(db.String(50), nullable=True, default="")
    feedback_date = db.Column(db.Date, nullable=True)
    feedback_time = db.Column(db.String(20), nullable=True, default="")
    message = db.Column(db.Text)
    image_filename = db.Column(db.String(200), nullable=True)
    submitted_at = db.Column(db.DateTime, default=db.func.now())
    status = db.Column(db.String(50), default="Pending")
    forwarded_to_chief = db.Column(db.Boolean, default=False)
    forwarded_at = db.Column(db.DateTime, nullable=True)
    solved_at = db.Column(db.DateTime, nullable=True)
    rating = db.Column(db.Integer, nullable=True)
    rating_comment = db.Column(db.Text, nullable=True, default="")
    solution_note = db.Column(db.Text, nullable=True, default="")
    student = db.relationship('Student', backref=db.backref('food_complaints', lazy=True))


class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(100))
    email = db.Column(db.String(100), nullable=True)
    role = db.Column(db.String(50), default='warden')
    security_question_1 = db.Column(db.String(100), nullable=True)
    security_answer_1 = db.Column(db.String(100), nullable=True)
    security_question_2 = db.Column(db.String(100), nullable=True)
    security_answer_2 = db.Column(db.String(100), nullable=True)


class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=True)
    password = db.Column(db.String(100), nullable=True)
    name = db.Column(db.String(100), nullable=False)
    student_class = db.Column(db.String(50), nullable=False)
    phone_number = db.Column(db.String(20), nullable=False)
    parent_phone = db.Column(db.String(20), nullable=False)
    parent_email = db.Column(db.String(100), nullable=True, default="")
    class_incharge_email = db.Column(db.String(100), nullable=True, default="")
    room_number = db.Column(db.String(20), nullable=True, default="")
    email = db.Column(db.String(100), nullable=True, default="")
    security_question_1 = db.Column(db.String(100), nullable=True)
    security_answer_1 = db.Column(db.String(100), nullable=True)
    security_question_2 = db.Column(db.String(100), nullable=True)
    security_answer_2 = db.Column(db.String(100), nullable=True)
    registered_at = db.Column(db.DateTime, default=db.func.now())
    attendances = db.relationship('Attendance', backref='student', lazy=True, cascade='all, delete-orphan')


class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='Absent')
    marked_at = db.Column(db.DateTime, default=db.func.now())

    __table_args__ = (db.UniqueConstraint('student_id', 'date', name='unique_student_date'),)


class LeaveRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    leave_message = db.Column(db.Text, nullable=False)
    from_date = db.Column(db.Date, nullable=True)
    to_date = db.Column(db.Date, nullable=True)
    parent_status = db.Column(db.String(50), default='Pending')
    parent_rejection_reason = db.Column(db.Text, nullable=True, default="")
    teacher_status = db.Column(db.String(50), default='Pending')
    teacher_rejection_reason = db.Column(db.Text, nullable=True, default="")
    forwarded_to_warden = db.Column(db.Boolean, default=False)
    warden_status = db.Column(db.String(50), default='Pending')
    warden_rejection_reason = db.Column(db.Text, nullable=True, default="")
    status = db.Column(db.String(50), default='Pending')
    rejection_reason = db.Column(db.Text, nullable=True, default="")
    submitted_at = db.Column(db.DateTime, default=db.func.now())
    student = db.relationship('Student', backref=db.backref('leave_requests', lazy=True))


class RoomIssue(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    room_number = db.Column(db.String(20), nullable=True, default="")
    issue_type = db.Column(db.String(50), default='General Maintenance')
    issue_date = db.Column(db.Date, nullable=True)
    issue_time = db.Column(db.String(20), nullable=True, default="")
    message = db.Column(db.Text, nullable=False)
    image_filename = db.Column(db.String(200), nullable=True)
    status = db.Column(db.String(50), default='Pending')
    forwarded_to = db.Column(db.String(50), nullable=True, default="")
    forwarded_at = db.Column(db.DateTime, nullable=True)
    admin_note = db.Column(db.Text, nullable=True, default="")
    solved_at = db.Column(db.DateTime, nullable=True)
    rating = db.Column(db.Integer, nullable=True)
    rating_comment = db.Column(db.Text, nullable=True, default="")
    solution_note = db.Column(db.Text, nullable=True, default="")
    submitted_at = db.Column(db.DateTime, default=db.func.now())
    student = db.relationship('Student', backref=db.backref('room_issues', lazy=True))


class Parent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=True)
    password = db.Column(db.String(100), nullable=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    student_name = db.Column(db.String(100), nullable=False)
    student_email = db.Column(db.String(100), nullable=False)
    phone_number = db.Column(db.String(20), nullable=True, default="")
    security_question_1 = db.Column(db.String(100), nullable=True)
    security_answer_1 = db.Column(db.String(100), nullable=True)
    security_question_2 = db.Column(db.String(100), nullable=True)
    security_answer_2 = db.Column(db.String(100), nullable=True)
    registered_at = db.Column(db.DateTime, default=db.func.now())


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    parent_email = db.Column(db.String(100), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=db.func.now())