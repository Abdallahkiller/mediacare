import pyodbc
import json
import os
from flask import Flask, render_template, request, redirect, url_for, session, flash

app = Flask(__name__)
app.secret_key = '123'
CONFIG_FILE = 'db_config.json'

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_config(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f)

def get_db_connection():
    config = load_config()
    if not config.get('server') or not config.get('database'):
        return None
    try:
        connection = pyodbc.connect(
            f"DRIVER={{SQL Server}};"
            f"SERVER={config['server']};"
            f"DATABASE={config['database']};"
            f"Trusted_Connection=yes;"
        )

        return connection
    except Exception as e:
        print("Connection Error:", e)
        return None

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if 'username' not in session:
        return redirect(url_for('login'))

    if session.get('Role') != 'مدير':
        return "هذه الصفحة مخصصة للمدير فقط.", 403  # أو تقدر تعيد توجيه المستخدم لصفحة أخرى
    current_config = load_config()

    if request.method == 'POST':
        new_config = {
            'server': request.form['server'],
            'database': request.form['database']
        }
        save_config(new_config)
        return redirect(url_for('login'))

    return render_template('settings.html', config=current_config)

@app.route('/report')
def index():
    if 'username' not in session:
        return redirect(url_for('login'))

    if session.get('Role') != 'مدير':
        return "هذه الصفحة مخصصة للمدير فقط.", 403

    from_date = request.args.get('from_date')
    to_date = request.args.get('to_date')
    invoice_type = request.args.get('invoice_type')  # كاش - أجل - مرتجع

    conn = get_db_connection()
    if not conn:
        return redirect(url_for('settings'))

    cursor = conn.cursor()

    def filter_query(base_query, conditions, params):
        if conditions:
            base_query += " WHERE " + " AND ".join(conditions)
        return base_query, params

    # الفلاتر المشتركة
    common_conditions = []
    params = []
    net_cash1 = []
    net_cash2 = []


    if from_date and to_date:
        common_conditions.append("InvoiceDate BETWEEN ? AND ?")
        params.extend([from_date, to_date])

    # مبيعات كاش
    if invoice_type in ("", "كاش", None):
        query, q_params = filter_query("SELECT SUM(CAST(TotalAmount AS FLOAT)) FROM Invoices", list(common_conditions), list(params))
        cursor.execute(query, q_params)
        cash_sales = cursor.fetchone()[0] or 0
    else:
        cash_sales = 0

    # مبيعات آجل
    if invoice_type in ("", "أجل", None):
        query, q_params = filter_query("SELECT SUM(CAST(TotalAmount AS FLOAT)) FROM Invoices2", list(common_conditions), list(params))
        cursor.execute(query, q_params)
        credit_sales = cursor.fetchone()[0] or 0
    else:
        credit_sales = 0

    # المرتجعات
    if invoice_type in ("", "مرتجع", None):
        query, q_params = filter_query("SELECT SUM(CAST(TotalAmount AS FLOAT)) FROM Invoices1", list(common_conditions), list(params))
        cursor.execute(query, q_params)
        return_sales = cursor.fetchone()[0] or 0
    else:
        return_sales = 0

    total_sarf = sum([row[2] or 0 for row in net_cash1])  # row[1] هو SUM(sarf)
    # إجمالي الاستلام
    total_estlam = sum([row[2] or 0 for row in net_cash2])  # row[1] هو SUM(estlam)
    # الإجمالي
    net_sales = cash_sales + credit_sales - return_sales
    total = cash_sales + credit_sales + total_estlam - return_sales - total_sarf

    # مبيعات يومية (من جدول Invoices1)
    cursor.execute("""
        SELECT InvoiceDate, SUM(TotalAmount) 
        FROM Invoices1 
        GROUP BY InvoiceDate 
        ORDER BY InvoiceDate DESC
    """)
    daily_sales = cursor.fetchall()

    # استلام وسرف من accountofcustomer2
    cursor.execute("""
        SELECT SUM(sarf) 
        FROM accountofcustomer2 
    """)
    net_cash1 = cursor.fetchall()

    cursor.execute("""
        SELECT SUM(estlam) 
        FROM accountofcustomer2 
    """)
    net_cash2 = cursor.fetchall()

    # المنتجات الأعلى
    cursor.execute("""
        SELECT ProductName, SUM(Quantity)
        FROM InvoiceDetails 
        GROUP BY ProductName 
        ORDER BY SUM(Quantity) DESC
    """)
    top_products = cursor.fetchall()

    conn.close()

    return render_template('reports.html',
                           cash_sales=cash_sales,
                           credit_sales=credit_sales,
                           return_sales=return_sales,
                           net_sales=net_sales,
                           net_cash1=net_cash1,
                           net_cash2=net_cash2,
                           total_sarf=total_sarf,
                           total_estlam=total_estlam,
                           daily_sales=daily_sales,
                           top_products=top_products,
                           from_date=from_date,
                           to_date=to_date,
                           total=total,
                           invoice_type=invoice_type
    )


# صفحة تسجيل الدخول
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db_connection()
        if not conn:
            flash("يرجى ضبط إعدادات الاتصال أولاً", "error")
            return redirect(url_for('settings'))

        cursor = conn.cursor()
        cursor.execute("SELECT UserID, Role FROM Users1 WHERE UserID = ? AND Password = ?", (username, password))
        user = cursor.fetchone()
        conn.close()

        if user:
            session['username'] = user.UserID
            session['Role'] = user.Role  # نحفظ الصلاحية
            return redirect(url_for('index'))
        else:
            flash("بيانات الدخول غير صحيحة", "error")
            return redirect(url_for('login'))

    return render_template('login.html')



# تسجيل الخروج
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)