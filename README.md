## syh's chatter

### 配置环境
* syh's chatter聊天器使用了Python语言、Flask架构与MongoDB数据库
* 您可以使用以下命令来配置Python环境（确保您已经安装了pip且有MongoDB的服务器）

  `pip install flask pymongo`

### 安装
* 使用以下命令下载并进入目录：

  ```
  git clone https://github.com/syh100925/syh-s-chatter.git
  cd syh-s-chatter
  ```

### 启动前的设置
* 打开`server.py`，可以使用`nano server.py`，也可以`vim server.py`等等
  * 编辑以下字段：
    ```
    user_list = {'admin': ['666', 'grey'],
             'syh': ['ccc', 'yellow'],
             'Star': ['eee', 'LightBlue']
            }

    database_ip = '127.0.0.1'
    database_port = '27017'
    database_user = 'user'
    database_password = 'password'
    ```

  * `server_ip`：服务器的ip地址
  * `user_list`：用户名字典（注意：编辑时保留`admin`账户，`admin`的密码可以更改）
    * 字典的键：用户名
    * 字典的值的第一项：该用户的密码
    * 字典的值的第二项：该用户的颜色
  * `database_ip`：`MongoDB`数据库的地址
  * `database_port`：`MongoDB`数据库的端口（默认27017）
  * `database_user`：`MongoDB`数据库的用户名
  * `database_password`：`MongoDB`数据库的密码

### 快速启动
* syh's chatter仅凭一行命令即可运行：
  #### 对于Windows&Linux：
  * 环境需求：Python3、Flask
  
    `python server.py`
    或
    `python3 server.py`
  
  #### 后台运行（仅Linux）：
  * 环境需求：Linux系统（带nohup命令）
  * 使用命令：
    * 启动：`./start.sh`
    * 停止：`./stop.sh`之后会返回一个[PID]，使用`kill [PID]`来结束
    * 重置：登录聊天室的admin账户，输入`clear`即可

### 更多设置
* 在`templates`目录下，有`login.html`和`chat.html`
* 你可以通过修改两个文件里面的`style`标签来达到不同的效果


* 在`chat.html`文件中，有以下字段：
  ```
  setInterval(update, 1 * 1000);
  setInterval(login, 5 * 60 * 1000);
  ```
  * 在第一行中，您可以通过修改`1 * 1000`（单位：ms）来修改从服务器获取数据的时间间隔
  * 在第二行中，您可以通过修改`5 * 60 * 1000`（单位：ms）来修改自动登出的时间


