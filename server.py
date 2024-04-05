from flask import Flask, render_template, request, redirect
import time
import random
from pymongo import MongoClient
import logging


server_ip = '127.0.0.1:8080'

user_list = {'admin': ['666', 'grey'],
             'syh': ['ccc', 'yellow'],
             'Star': ['eee', 'LightBlue']
            }

database_ip = '127.0.0.1'
database_port = '27017'
database_user = 'user'
database_password = 'password'


usernames = []
passwords = []
user_colors = []
for i in user_list:
    usernames.append(i)
    passwords.append(user_list[i][0])
    user_colors.append(user_list[i][1])

client = MongoClient('mongodb://' + database_user + ':' + database_password + '@' + database_ip + ':' + database_port)

db = client['chats']
database = db['values']

if len(db.list_collection_names()) == 0:
    database.insert_one({'chat': 'clear', 'user': 'admin', 'color': 'grey', 'time': 'unknown'})

d_c = 0
for data in database.find():
    d_c += 1
if d_c < 20:
    for _ in range(20 - d_c):
        database.insert_one({'chat': '', 'user': '', 'color': '', 'time': ''})


app = Flask(__name__)


# syh's chatter --------------------------------------------------------------------------

'''
open('chats.txt', 'a')
open('users.txt', 'a')
open('times.txt', 'a')
open('colors.txt', 'a')
'''

open('login_users.txt', 'a')
open('login_passes.txt', 'a')

ip = server_ip


'''
users = open('users.txt', 'r').read().split('\n')
chats = open('chats.txt', 'r').read().split('\n')
times = open('times.txt', 'r').read().split('\n')
colors = open('colors.txt', 'r').read().split('\n')

for i in range(20 - len(chats)):
    chats.append('')

for i in range(20 - len(users)):
    users.append('')

for i in range(20 - len(times)):
    times.append('')

for i in range(20 - len(colors)):
    colors.append('')
'''


def get_data():
    chats = []
    users = []
    colors = []
    times = []
    for i in database.find():
        chats.append(i['chat'])
        users.append(i['user'])
        colors.append(i['color'])
        times.append(i['time'])
    for _ in range(20 - len(chats)):
        chats.append('')
        users.append('')
        colors.append('')
        times.append('')
    return [chats, users, colors, times]

def add_chat(chats, users, colors, times, username, value, d_time):
    if users[-1] == '':
        for i in range(20):
            if users[i] == '':
                users[i] = username
                chats[i] = value
                times[i] = d_time
                colors[i] = user_colors[usernames.index(username)]
                break

    else:
        for i in range(19):
            users[i] = users[i + 1]
            chats[i] = chats[i + 1]
            times[i] = times[i + 1]
            colors[i] = colors[i + 1]

        users[-1] = username
        chats[-1] = value
        times[-1] = d_time
        colors[-1] = user_colors[usernames.index(username)]

    if username == 'admin':
        users = ['admin']
        chats = ['clear']
        times = ['unknown']
        colors = ['grey']
        for i in range(19):
            users.append('')
            chats.append('')
            times.append('')
            colors.append('')

    save_chats(chats, users, colors, times)

def save_chats(chats, users, colors, times):
    for i in range(20):
        database.replace_one(database.find()[i], {'chat': chats[i], 'user': users[i], 'color': colors[i], 'time': times[i]}, upsert=True)


@app.route('/')
def normal():
    return render_template('login.html')

@app.route('/logout')
def logout():
    return redirect('/')

@app.route('/error')
def error():
    return render_template('login.html')
'''
@app.route('/file')
def file():
    return render_template('file.html')

@app.route('/file', methods=['POST'])
def upload_file():
    uploaded_file = request.files['file']
    if uploaded_file.filename != '':
        uploaded_file.save(uploaded_file.filename)
    return render_template('file_done.html')
'''
@app.route('/chats', methods=['POST'])
def chats():
    username = request.form.get('username')
    update = request.form.get('update')
    a = open('login_users.txt', 'r').read().split('\n')
    b = open('login_passes.txt', 'r').read().split('\n')
    logining_users = {}
    for i in range(len(a)):
        logining_users[a[i]] = [int(b[i])]
    if not str(logining_users[username][0]) == update:
        return '认证数据错误\n聊天室\nred\nunknown'

    chats, users, colors, times = get_data()
    r = ''
    for i in chats:
        r += i + ' || '
    r = r[: -4] + '\n'
    for i in users:
        r += i + ' || '
    r = r[: -4] + '\n'
    for i in colors:
        r += i + ' || '
    r = r[: -4] + '\n'
    for i in times:
        r += i + ' || '

    return r

@app.route('/chat_file', methods=['GET', 'POST'])
def chat_file():
    chats, users, colors, times = get_data()
    a = open('login_users.txt', 'r').read().split('\n')
    b = open('login_passes.txt', 'r').read().split('\n')
    logining_users = {}
    for i in range(len(a)):
        logining_users[a[i]] = [int(b[i])]

    upf = request.files['file']
    ip = request.args.get('update')
    if upf.filename != '':
        upf.save('static/uploads/' + upf.filename)
        if ip == None:
            ip = 0
        else:
            ip = int(ip)
        username = 'unknown'

        d_time = time.localtime()
        d_hour = str(d_time.tm_hour)
        d_min = str(d_time.tm_min)
        if len(d_hour) == 1:
            d_hour = '0' + d_hour
        if len(d_min) == 1:
            d_min = '0' + d_min
        d_time = d_hour + ':' + d_min

        for i in logining_users:
            if str(logining_users[i][0]) == str(ip):
                username = i

        if username == None:
            return redirect('/chat?update=' + str(ip))

        value = '::file::' + upf.filename

        add_chat(chats, users, colors, times, username, value, d_time)

    return redirect('/chat?update=' + str(ip))

@app.route('/chat', methods=['GET', 'POST'])
def chat():
    chats, users, colors, times = get_data()

    a = open('login_users.txt', 'r').read().split('\n')
    b = open('login_passes.txt', 'r').read().split('\n')

    if a == ['']:
        a = []
        b = []

    text = request.args.get('text')
    if text == None:
        text = ''
    text = str(text)

    logining_users = {}
    if len(a) != 0:
        for i in range(len(a)):
            logining_users[a[i]] = [int(b[i]), time.time()]

    username = None
    password = None
    r = None

    try:
        r = int(request.args.get('update'))

    except:
        pass

    for i in logining_users:
        if logining_users[i][0] == r:
            if time.time() - logining_users[i][1] > 3 * 60:
                del logining_users[i]
                l_users = ''
                l_passes = ''
                for i in logining_users:
                    l_users += i + '\n'
                    l_passes += str(logining_users[i][0]) + '\n'
                l_users = l_users[ : -1]
                l_passes = l_passes[ : -1]

                open('login_users.txt', 'w').write(l_users)
                open('login_passes.txt', 'w').write(l_passes)

            else:
                username = i
                password = passwords[usernames.index(username)]

    if username == None and password == None:
        username = str(request.form.get('username'))
        password = str(request.form.get('password'))

    if username in usernames and passwords[usernames.index(username)] == password:
        logining_users[username] = [random.randint(1000000000, 10000000000 - 1), time.time()]

        l_users = ''
        l_passes = ''
        for i in logining_users:
            l_users += i + '\n'
            l_passes += str(logining_users[i][0]) + '\n'
        l_users = l_users[ : -1]
        l_passes = l_passes[ : -1]

        open('login_users.txt', 'w').write(l_users)
        open('login_passes.txt', 'w').write(l_passes)

        e_update = logining_users[username][0]

        return render_template('chat.html', text=text, username=username, update=e_update, self_ip=ip, jump_ip='http://' + ip + '/chat?update=' + str(e_update))
    else:
        return redirect('/error')

@app.route('/chat-new', methods=['POST', 'GET'])
def chat_new():
    chats, users, colors, times = get_data()
    a = open('login_users.txt', 'r').read().split('\n')
    b = open('login_passes.txt', 'r').read().split('\n')
    logining_users = {}
    for i in range(len(a)):
        logining_users[a[i]] = [int(b[i])]

    value = str(request.form.get('upload_value'))
    ip = request.args.get('update')
    if ip == None:
        ip = 0
    else:
        ip = int(ip)

    username = 'unknown'

    d_time = time.localtime()
    # d_time = str(d_time.tm_mon) + ':' + str(d_time.tm_mday) + ':' + str(d_time.tm_hour) + ':' + str(d_time.tm_min) + ':' + str(d_time.tm_sec)
    d_hour = str(d_time.tm_hour)
    d_min = str(d_time.tm_min)
    if len(d_hour) == 1:
        d_hour = '0' + d_hour
    if len(d_min) == 1:
        d_min = '0' + d_min
    d_time = d_hour + ':' + d_min

    for i in logining_users:
        if str(logining_users[i][0]) == str(ip):
            username = i

    if username == 'unknown':
        return redirect('/chat?update=' + str(ip))

    add_chat(chats, users, colors, times, username, value, d_time)

    '''
    n_users = ''
    for i in users:
        n_users += i + '\n'

    n_users = n_users[ : -1]
    open('users.txt', 'w').write(n_users)

    n_chats = ''
    for i in chats:
        n_chats += i + '\n'

    n_chats = n_chats[ : -1]
    open('chats.txt', 'w').write(n_chats)

    n_time = ''
    for i in times:
        n_time += i + '\n'

    n_time = n_time[ : -1]
    open('times.txt', 'w').write(n_time)

    n_colors = ''
    for i in colors:
        n_colors += i + '\n'

    n_colors = n_colors[ : -1]
    open('colors.txt', 'w').write(n_colors)
    '''

    return redirect('/chat?update=' + str(ip))

if __name__ == '__main__':
    app.run(port=8080, debug=True)
