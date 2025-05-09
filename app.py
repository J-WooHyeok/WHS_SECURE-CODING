import sqlite3
import uuid
import os
import bcrypt

from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from flask_socketio import SocketIO, send
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
DATABASE = 'market.db'
socketio = SocketIO(app)

UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# 사진 추가시 사진 이름 변경
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# 데이터베이스 연결 관리: 요청마다 연결 생성 후 사용, 종료 시 close
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row  # 결과를 dict처럼 사용하기 위함
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# 테이블 생성 (최초 실행 시에만)
def init_db():
    with app.app_context():
        db = get_db()
        cursor = db.cursor()
        # 사용자 테이블 생성
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                bio TEXT
            )
        """)
        # 상품 테이블 생성
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS product (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                price TEXT NOT NULL,
                seller_id TEXT NOT NULL
            )
        """)
        # 신고 테이블 생성
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS report (
                id TEXT PRIMARY KEY,
                reporter_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                reason TEXT NOT NULL
            )
        """)
        db.commit()

# 신고 횟수 조회 함수
def get_report_count_by_target(target_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT COUNT(*) FROM report WHERE target_id = ?", (target_id,))
    result = cursor.fetchone()
    return result[0] if result else 0

# 기본 라우트
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

# 회원가입
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db()
        cursor = db.cursor()
        # 중복 사용자 체크
        cursor.execute("SELECT * FROM user WHERE username = ?", (username,))
        if cursor.fetchone() is not None:
            flash('이미 존재하는 사용자명입니다.')
            return redirect(url_for('register'))
        user_id = str(uuid.uuid4())
        hashed_pw = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        cursor.execute("INSERT INTO user (id, username, password) VALUES (?, ?, ?)",
                       (user_id, username, hashed_pw))
        db.commit()
        flash('회원가입이 완료되었습니다. 로그인 해주세요.')
        return redirect(url_for('login'))
    return render_template('register.html')

# 로그인
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT * FROM user WHERE username = ?", (username,))
        user = cursor.fetchone()
        if user and bcrypt.checkpw(password.encode('utf-8'), user['password']):
            session['user_id'] = user['id']
            flash('로그인 성공!')
            return redirect(url_for('dashboard'))
        else:
            flash('아이디 또는 비밀번호가 올바르지 않습니다.')
            return redirect(url_for('login'))
    return render_template('login.html')

# 로그아웃
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('로그아웃되었습니다.')
    return redirect(url_for('index'))

# 대시보드: 사용자 정보와 전체 상품 리스트 표시
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    db = get_db()
    cursor = db.cursor()
    # 현재 사용자 조회
    cursor.execute("SELECT * FROM user WHERE id = ?", (session['user_id'],))
    current_user = cursor.fetchone()
    # 모든 상품 조회
    cursor.execute("SELECT * FROM product")
    all_products = cursor.fetchall()
    return render_template('dashboard.html', products=all_products, user=current_user)

# 프로필 페이지: bio 업데이트 가능
@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    db = get_db()
    cursor = db.cursor()
    if request.method == 'POST':
        bio = request.form.get('bio', '')
        cursor.execute("UPDATE user SET bio = ? WHERE id = ?", (bio, session['user_id']))
        db.commit()
        flash('프로필이 업데이트되었습니다.')
        return redirect(url_for('profile'))
    
    # 내 정보 가져오기
    cursor.execute("SELECT * FROM user WHERE id = ?", (session['user_id'],))
    current_user = cursor.fetchone()

    # 내가 등록한 상품 가져오기
    cursor.execute("SELECT * FROM product WHERE seller_id = ?", (session['user_id'],))
    my_products = cursor.fetchall()

    return render_template('profile.html', user=current_user, products=my_products)

# 상품 등록
@app.route('/product/new', methods=['GET', 'POST'])
def new_product():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        price = request.form['price']
        image_file = request.files.get('image')
        image_filename = None

        if image_file and allowed_file(image_file.filename):
            filename = secure_filename(image_file.filename)
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            image_file.save(image_path)
            image_filename = filename

        db = get_db()
        cursor = db.cursor()
        product_id = str(uuid.uuid4())

        cursor.execute(
            "INSERT INTO product (id, title, description, price, seller_id, image_filename) VALUES (?, ?, ?, ?, ?, ?)",
            (product_id, title, description, price, session['user_id'], image_filename)
        )
        db.commit()
        flash('상품이 등록되었습니다.')
        return redirect(url_for('dashboard'))

    return render_template('new_product.html')


# 상품 삭제
@app.route('/product/delete/<product_id>', methods=['GET'])
def delete_product(product_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    db = get_db()
    cursor = db.cursor()
    
    # 해당 상품을 만든 사람만 삭제 가능
    cursor.execute("SELECT * FROM product WHERE id = ? AND seller_id = ?", (product_id, session['user_id']))
    product = cursor.fetchone()
    
    if not product:
        flash('상품을 삭제할 수 없습니다.')
        return redirect(url_for('profile'))
    
    cursor.execute("DELETE FROM product WHERE id = ?", (product_id,))
    db.commit()
    flash('상품이 삭제되었습니다.')
    return redirect(url_for('profile'))

# 상품 수정
@app.route('/product/edit/<product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    db = get_db()
    cursor = db.cursor()

    # 내 상품인지 확인
    cursor.execute("SELECT * FROM product WHERE id = ? AND seller_id = ?", (product_id, session['user_id']))
    product = cursor.fetchone()

    if not product:
        flash('상품을 수정할 수 없습니다.')
        return redirect(url_for('profile'))

    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        price = request.form['price']
        cursor.execute("UPDATE product SET title = ?, description = ?, price = ? WHERE id = ?", 
                       (title, description, price, product_id))
        db.commit()
        flash('상품이 수정되었습니다.')
        return redirect(url_for('profile'))

    # GET 방식일 때 수정 폼 보여주기
    return render_template('edit_product.html', product=product)


# 상품 상세보기
@app.route('/product/<product_id>')
def view_product(product_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM product WHERE id = ?", (product_id,))
    product = cursor.fetchone()

    if not product:
        flash('상품을 찾을 수 없습니다.')
        return redirect(url_for('dashboard'))

    # 판매자 정보
    cursor.execute("SELECT * FROM user WHERE id = ?", (product['seller_id'],))
    seller = cursor.fetchone()

    # ✅ 해당 상품의 신고 수 조회
    report_count = get_report_count_by_target(product_id)

    return render_template(
        'view_product.html',
        product=product,
        seller=seller,
        report_count=report_count
    )


# 신고하기
@app.route('/report', methods=['GET', 'POST'])
def report():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    db = get_db()
    cursor = db.cursor()

    if request.method == 'POST':
        target_id = request.form['target_id']
        reason = request.form['reason']

        report_id = str(uuid.uuid4())
        cursor.execute(
            "INSERT INTO report (id, reporter_id, target_id, reason) VALUES (?, ?, ?, ?)",
            (report_id, session['user_id'], target_id, reason)
        )
        db.commit()

        # ✅ 사용자 신고 누적 확인 및 휴면 처리
        cursor.execute("SELECT * FROM user WHERE id = ?", (target_id,))
        reported_user = cursor.fetchone()

        if reported_user:
            count = get_report_count_by_target(target_id)
            if count >= 5:
                cursor.execute("UPDATE user SET status = 'dormant' WHERE id = ?", (target_id,))
                db.commit()
                flash('신고 누적으로 해당 사용자가 휴면 계정으로 전환되었습니다.')

        flash('신고가 접수되었습니다.')
        return redirect(url_for('dashboard'))

    # GET 요청일 경우: 쿼리 파라미터로 target_id 전달됨
    target_id = request.args.get('target_id', '')
    return render_template('report.html', target_id=target_id)


# 비밀번호 변경
@app.route('/change_password', methods=['POST'])
def change_password():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    current_password = request.form['current_password']
    new_password = request.form['new_password']

    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT password FROM user WHERE id = ?", (session['user_id'],))
    user = cursor.fetchone()

    if user and bcrypt.checkpw(current_password.encode('utf-8'), user['password']):
        new_hashed_pw = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt())
        cursor.execute("UPDATE user SET password = ? WHERE id = ?", (new_hashed_pw, session['user_id']))
        db.commit()
        flash('비밀번호가 성공적으로 변경되었습니다.')
    else:
        flash('현재 비밀번호가 일치하지 않습니다.')

    return redirect(url_for('profile'))


# 판매자와 채팅하기
@app.route('/chat/<product_id>')
def chat(product_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    db = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT * FROM product WHERE id = ?", (product_id,))
    product = cursor.fetchone()

    cursor.execute("SELECT * FROM user WHERE id = ?", (product['seller_id'],))
    seller = cursor.fetchone()

    # 이전 채팅 불러오기
    cursor.execute("""
        SELECT username, message, timestamp FROM chat_message
        WHERE product_id = ?
        ORDER BY timestamp ASC
    """, (product_id,))
    chat_history = cursor.fetchall()

    return render_template('chat.html', product=product, seller=seller, chat_history=chat_history)


# 실시간 채팅: 전체 채팅, 판매자 채팅
@socketio.on('send_message')
def handle_send_message_event(data):
    db = get_db()
    cursor = db.cursor()

    user_id = session.get('user_id')
    if not user_id:
        return

    cursor.execute("SELECT username FROM user WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    username = user['username'] if user else '알 수 없음'

    product_id = data.get('product_id')
    message = data.get('message')
    message_id = str(uuid.uuid4())

    # ✅ product_id와 함께 DB에 저장
    cursor.execute("""
        INSERT INTO chat_message (id, product_id, username, message)
        VALUES (?, ?, ?, ?)
    """, (message_id, product_id, username, message))
    db.commit()

    # 클라이언트에 메시지 전송
    send({
        'message_id': message_id,
        'username': username,
        'message': message
    }, broadcast=True)




if __name__ == '__main__':
    init_db()  # 앱 컨텍스트 내에서 테이블 생성
    socketio.run(app, debug=True)





