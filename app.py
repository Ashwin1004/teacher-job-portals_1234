import sqlite3
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import os
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'educonnect-super-secret-key-123'

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'teacher_portal.db')

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Users
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
        role TEXT CHECK(role IN ('teacher','recruiter')) NOT NULL
    )''')
    # Teacher Profiles
    cursor.execute('''CREATE TABLE IF NOT EXISTS teacher_profiles (
        user_id INTEGER PRIMARY KEY, qualification TEXT,
        skills TEXT, experience TEXT, phone TEXT, resume_link TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')
    # Jobs
    cursor.execute('''CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, recruiter_id INTEGER,
        title TEXT NOT NULL, subject TEXT NOT NULL,
        salary TEXT, location TEXT, description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (recruiter_id) REFERENCES users(id)
    )''')
    # Applications
    cursor.execute('''CREATE TABLE IF NOT EXISTS applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER,
        teacher_id INTEGER, status TEXT DEFAULT 'Pending',
        applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (job_id) REFERENCES jobs(id),
        FOREIGN KEY (teacher_id) REFERENCES users(id),
        UNIQUE(job_id, teacher_id)
    )''')
    conn.commit()
    conn.close()

init_db()

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@app.context_processor
def inject_user():
    return dict(session=session)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name, email, password, role = request.form.get('name'), request.form.get('email'), request.form.get('password'), request.form.get('role')
        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'error')
            return redirect(url_for('register'))
        hashed_password = generate_password_hash(password)
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO users (name, email, password, role) VALUES (?, ?, ?, ?)", (name, email, hashed_password, role))
            user_id = cursor.lastrowid
            if role == 'teacher':
                cursor.execute("INSERT INTO teacher_profiles (user_id) VALUES (?)", (user_id,))
            conn.commit()
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Email already registered.', 'error')
        finally:
            conn.close()
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email, password = request.form.get('email'), request.form.get('password')
        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        conn.close()
        if user and check_password_hash(user['password'], password):
            session['user_id'], session['name'], session['role'] = user['id'], user['name'], user['role']
            flash(f'Welcome back, {user["name"]}!', 'success')
            return redirect(url_for('teacher_dashboard') if user['role'] == 'teacher' else url_for('recruiter_dashboard'))
        flash('Invalid email or password.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():     
    session.clear()
    flash('Logged out.', 'success')
    return redirect(url_for('login'))

@app.route('/teacher_dashboard')
def teacher_dashboard():
    if session.get('role') != 'teacher': return redirect(url_for('login'))
    conn = get_db_connection()
    profile = conn.execute("SELECT * FROM teacher_profiles WHERE user_id = ?", (session['user_id'],)).fetchone()
    # Applied Jobs
    applications = conn.execute('''
        SELECT j.title, j.location, j.salary, u.name as school_name, a.status, a.applied_at 
        FROM applications a 
        JOIN jobs j ON a.job_id = j.id
        JOIN users u ON j.recruiter_id = u.id
        WHERE a.teacher_id = ? ORDER BY a.applied_at DESC
    ''', (session['user_id'],)).fetchall()
    conn.close()
    return render_template('teacher_dashboard.html', profile=profile, applications=applications)

@app.route('/edit_profile', methods=['GET', 'POST'])
def edit_profile():
    if session.get('role') != 'teacher':
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    if request.method == 'POST':
        qualification = request.form['qualification']
        skills = request.form['skills']
        experience = request.form['experience']
        phone = request.form.get('phone', '')
        resume_link = request.form.get('resume_link', '')
        
        # Check if profile exists
        prof = conn.execute("SELECT * FROM teacher_profiles WHERE user_id=?", (session['user_id'],)).fetchone()
        if prof:
            conn.execute("UPDATE teacher_profiles SET qualification=?, skills=?, experience=?, phone=?, resume_link=? WHERE user_id=?", 
                         (qualification, skills, experience, phone, resume_link, session['user_id']))
        else:
            conn.execute("INSERT INTO teacher_profiles (user_id, qualification, skills, experience, phone, resume_link) VALUES (?, ?, ?, ?, ?, ?)", 
                         (session['user_id'], qualification, skills, experience, phone, resume_link))
        conn.commit()
        flash("Profile updated successfully!", "success")
        conn.close()
        return redirect(url_for('teacher_dashboard'))
    
    profile = conn.execute("SELECT * FROM teacher_profiles WHERE user_id=?", (session['user_id'],)).fetchone()
    conn.close()
    return render_template('profile_edit.html', profile=profile)

@app.route('/recruiter_dashboard')
def recruiter_dashboard():
    if session.get('role') != 'recruiter': return redirect(url_for('login'))
    conn = get_db_connection()
    jobs = conn.execute('''
        SELECT j.*, (SELECT COUNT(*) FROM applications WHERE job_id = j.id) as app_count 
        FROM jobs j WHERE recruiter_id = ? ORDER BY created_at DESC
    ''', (session['user_id'],)).fetchall()
    conn.close()
    return render_template('recruiter_dashboard.html', jobs=jobs)

@app.route('/post_job', methods=['GET', 'POST'])
def post_job():
    if session.get('role') != 'recruiter': return redirect(url_for('login'))
    if request.method == 'POST':
        conn = get_db_connection()
        conn.execute("INSERT INTO jobs (recruiter_id, title, subject, salary, location, description) VALUES (?,?,?,?,?,?)",
                     (session['user_id'], request.form.get('title'), request.form.get('subject'), 
                      request.form.get('salary'), request.form.get('location'), request.form.get('description')))
        conn.commit()
        conn.close()
        flash("Job posted successfully!", "success")
        return redirect(url_for('recruiter_dashboard'))
    return render_template('job_post.html')

@app.route('/delete_job/<int:job_id>')
def delete_job(job_id):
    if session.get('role') != 'recruiter': return redirect(url_for('login'))
    conn = get_db_connection()
    # Check ownership
    job = conn.execute("SELECT id FROM jobs WHERE id=? AND recruiter_id=?", (job_id, session['user_id'])).fetchone()
    if job:
        conn.execute("DELETE FROM applications WHERE job_id=?", (job_id,))
        conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        conn.commit()
        flash("Job deleted.", "success")
    conn.close()
    return redirect(url_for('recruiter_dashboard'))

@app.route('/jobs')
def job_listing():
    conn = get_db_connection()
    subject = request.args.get('subject', '')
    location = request.args.get('location', '')
    
    query = "SELECT j.*, u.name as school_name FROM jobs j JOIN users u ON j.recruiter_id = u.id WHERE 1=1"
    params = []
    
    if subject:
        query += " AND j.subject LIKE ?"
        params.append(f"%{subject}%")
    if location:
        query += " AND j.location LIKE ?"
        params.append(f"%{location}%")
        
    query += " ORDER BY j.created_at DESC"
    jobs = conn.execute(query, params).fetchall()
    conn.close()
    return render_template('jobs.html', jobs=jobs, subject=subject, location=location)

@app.route('/apply/<int:job_id>', methods=['POST'])
def apply_job(job_id):
    if session.get('role') != 'teacher':
        flash("Only teachers can apply for jobs.", "error")
        return redirect(url_for('job_listing'))
    conn = get_db_connection()
    try:
        conn.execute("INSERT INTO applications (job_id, teacher_id) VALUES (?, ?)", (job_id, session['user_id']))
        conn.commit()
        flash("Applied successfully!", "success")
    except sqlite3.IntegrityError:
        flash("You have already applied for this job.", "error")
    conn.close()
    return redirect(url_for('job_listing'))

@app.route('/job_applicants/<int:job_id>')
def job_applicants(job_id):
    if session.get('role') != 'recruiter': return redirect(url_for('login'))
    conn = get_db_connection()
    job = conn.execute("SELECT * FROM jobs WHERE id=? AND recruiter_id=?", (job_id, session['user_id'])).fetchone()
    if not job: 
        conn.close()
        return redirect(url_for('recruiter_dashboard'))
    
    apps = conn.execute('''SELECT a.*, u.name, u.email, t.qualification, t.skills, t.experience 
                           FROM applications a 
                           JOIN users u ON a.teacher_id=u.id 
                           JOIN teacher_profiles t ON a.teacher_id=t.user_id 
                           WHERE a.job_id=? ORDER BY a.applied_at DESC''', (job_id,)).fetchall()
    conn.close()
    return render_template('applicants.html', apps=apps, job=job)

@app.route('/update_application/<int:app_id>/<status>')
def update_application(app_id, status):
    if session.get('role') != 'recruiter': return redirect(url_for('login'))
    if status not in ['Shortlisted', 'Rejected']: return redirect(url_for('recruiter_dashboard'))
    conn = get_db_connection()
    owner = conn.execute("SELECT j.recruiter_id FROM applications a JOIN jobs j ON a.job_id=j.id WHERE a.id=?", (app_id,)).fetchone()
    if owner and owner['recruiter_id'] == session['user_id']:
        conn.execute("UPDATE applications SET status=? WHERE id=?", (status, app_id))
        conn.commit()
        flash(f"Application marked as {status}.", "success")
    conn.close()
    return redirect(request.referrer or url_for('recruiter_dashboard'))

if __name__ == '__main__':
    app.run(debug=True)
