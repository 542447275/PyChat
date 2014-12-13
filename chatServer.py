#! /usr/bin/python
# -*-  coding=utf8  -*-

#    Copyright (C) 2014 Guangmu Zhu <guangmuzhu@gmail.com>
#
#    This file is part of PyChat.
#
#    PyChat is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    PyChat is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with PyChat.  If not, see <http://www.gnu.org/licenses/>.

import socket
import threading
import thread
import signal
import time
import sys
import os
import subprocess
import tempfile

import readline
import datetime
import math

from Crypto.Cipher import AES

import pygame.camera, pygame.image, pygame.display, pygame.event
import pygame.mixer

# pynotify is not compatible with daemon
#    import pynotify

import traceback

HOST = None
PORT = 63333
ADDR = None
addr = None

udp_server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
udp_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

tcp_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
tcp_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

video_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
video_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

file_trans = None

instant_camera = None

BUFSIZE = 1024

row = 1
last_row = 0

message_flag = 0
last_message = None

last_time = None

last_heart_beat = None

history_fd = None

## !experiment!
is_you_leave = False

window_id = None
message_count = 0
message_sound = None

is_yy_on = False
## !experiment!

def sig_hdr(sig_num, frame):
    global addr, udp_server, tcp_server, video_server, history_fd
    
    if addr:
        try:
            udp_server.sendto(b'\x22\x22\x22', addr)
        except:
            pass
    
    udp_server.close()
    tcp_server.close()
    video_server.close()
    history_fd.flush()
    history_fd.close()
    pygame.mixer.stop()
    pygame.mixer.quit()
    os.system("pkill yyserver")
    os.system("pactl unload-module module-echo-cancel >&- 2>&-")
    sys.exit(0)

def sig_usr1_hdr(sig_num, frame):
    sys.stdout.write("\33[22;1H\33[2K\33[23;1H\33[2K\33[24;1H\33[2K\33[22;1H")
    sys.stdout.flush()
    if is_yy_on:
        is_yy_on = False
        print_in_mid("voice chat ended", isInfo = False)

def get_public_addr():
    ips = os.popen("/sbin/ifconfig | grep -E 'inet addr|inet' | awk '{print $2}'").readlines()
    for ip in ips:
        if ip.find("127.") == -1:
            return ip[ip.find(":") + 1:ip.find("\n")]

def cur_file_dir():
    path = sys.path[0]
    if os.path.isdir(path):
        return path
    elif os.path.isfile(path):
        return os.path.dirname(path)

def print_in_mid(line, isChat = True, isInfo = False):
    global row, last_row
    
    if line and len(line) <= 80:
        line = line.strip()
        if isChat:
            sys.stdout.write('\33[s\33[' + str(row) + ";" + str(40 - len(line) / 2 + 1) + 'H\33[33m' + line + '\33[0m\n\33[u')
        else:
            sys.stdout.write('\33[' + str(row) + ";" + str(40 - len(line) / 2 + 1) + 'H\33[33m' + line + '\33[0m\n')
        sys.stdout.flush()
        if isChat and not isInfo:
            history_fd.write("@" + line + "\n")
        last_row = 1
        row = row + last_row
        if isChat and row > 20:
            row = 20
        elif row > 24:
            row = 24

def wrap(data, left):
    global last_row
    
    data = data.decode("utf8")
    
    beg = 0
    count = 0
    lines = []
    for i in range(len(data)):
        if data[i] > u'\u00ff':
            count += 2
        else:
            count += 1
        if count > 48:
            lines.append(data[beg:i + 1])
            beg = i + 1
            count = 0
    if beg < len(data):
        lines.append(data[beg:])

    ret = ""
    if left:
        if count == 0:
            count = 50
        if len(lines) == 1:
            ret += "●"
            ret += "─" * (count + 2)
            ret += "┐\n"
            ret += "│ " + data.encode("utf8") + "\33[" + str(count + 4) + "G│\n└"
            ret += "─" * (count + 2)
            ret += "┘"
        else:
            ret += "●"
            ret += "─" * 52
            ret += "┐\n"
            for line in lines:
                ret += "│ " + line.encode("utf8") + "\33[54G│\n"
            ret += "└"
            ret += "─" * 52
            ret += "┘"
    else:
        if count == 0:
            count = 50
        if len(lines) == 1:
            ret += "\33[" + str(80 - count - 4) + "G┌"
            ret += "─" * (count + 2)
            ret += "┐\n"
            ret += "\33[" + str(80 - count - 4) + "G│ " + data.encode("utf8") + "\33[79G│\n\33[" + str(80 - count - 4) + "G└"
            ret += "─" * (count + 2)
            ret += "●"
        else:
            ret += "\33[26G┌"
            ret += "─" * 52
            ret += "┐\n"
            for line in lines:
                ret += "\33[26G│ " + line.encode("utf8") + "\33[79G│\n"
            ret += "\33[26G└"
            ret += "─" * 52
            ret += "●"
    last_row = len(lines) + 2
    return ret

class TMsg(threading.Thread):
    def run(self):
        global addr, udp_server, BUFSIZE, row, last_row, last_message, last_time, last_heart_beat, history_fd, is_you_leave, window_id, message_count, message_sound, is_yy_on
    
        try:
            while True:
                data, new_addr = udp_server.recvfrom(BUFSIZE)
                
                if data == "":
                    continue
            
                if data == b'\xAB\xCD\xEF':
                    udp_server.sendto(b'\xFE\xDC\xBA', new_addr)
                    if not last_heart_beat or addr != new_addr:
                        last_heart_beat = datetime.datetime.now()
                        addr = new_addr
                        print_in_mid("IP: " + addr[0] + " connected!", isInfo = True)
                        if int(os.popen("xdotool getwindowfocus").read().strip("\n")) != window_id:
                            os.popen("~/Apps/bin/notify-request PyChat \"IP: " + addr[0] + " connected!\" /usr/share/icons/hicolor/256x256/apps/cheese.png")
                            message_sound.play()
                    else:
                        last_heart_beat = datetime.datetime.now()
                        addr = new_addr
                elif data == b'\x11\x11\x11':
                    print_in_mid("Client left!", isInfo = True)
                    is_you_leave = True
                elif data == b'\x22\x22\x22':
                    print_in_mid("Client closed!", isInfo = True)
                elif data == "@yy":
                    if is_yy_on:
                        os.system("pkill yyclient")
                        is_yy_on = False
                        print_in_mid("voice chat ended", isInfo = False)
                    else:
                        os.system(os.environ["HOME"] + "/Apps/localchat/yyclient " + new_addr[0] + " &")
                        is_yy_on = True
                        print_in_mid("voice chat started", isInfo = False)
                else:
                    aes = AES.new(b'fuck your ass!??', AES.MODE_CBC, b'who is daddy!!??')
                    data = aes.decrypt(data).rstrip('\0')
                    if data[0] == '\0' and data[1] != '\0':
                        if is_you_leave:
                            print_in_mid("Client online!", isInfo = True)
                            is_you_leave = False
                        
                        addr = new_addr
                        
                        data = data[1:]
                        
                        aes = AES.new(b'fuck your ass!??', AES.MODE_CBC, b'who is daddy!!??')
                        udp_server.sendto(aes.encrypt("\0\0" + data[:data.find('\0')] + "\0" * (16 - (2 + data.find('\0')) % 16)), addr)
                        data = data[data.find('\0') + 1:]
            
                        if (datetime.datetime.now() - last_time).seconds > 300:
                            last_time = datetime.datetime.now()
                            print_in_mid(datetime.datetime.strftime(last_time, '%Y-%m-%d %H:%M:%S'))

                        sys.stdout.write('\33[s\33[' + str(row) + ';1H\33[34m' + wrap(data, True) + '\33[0m\n\33[u')
                        sys.stdout.flush()
                        history_fd.write("<" + data + "\n")
                        row = row + last_row
                        if row > 20:
                            row = 20
                        if int(os.popen("xdotool getwindowfocus").read().strip("\n")) != window_id:
                            os.popen("~/Apps/bin/notify-request PyChat \"" + data + "\" /usr/share/icons/hicolor/256x256/apps/cheese.png")
                            message_sound.play()
                            message_count += 1
                    elif new_addr == addr and data[0:2] == b"\0\0":
                        data = data[2:].rstrip("\0")
                        if int(data) == last_message:
                            last_message = None
        except Exception, e:
            os.system("zenity --error --text=\"" + str(e) + "\n" + traceback.format_exc() + "\"")
            sys.exit(1)

class TInput(threading.Thread):
    data = ""
    
    def run(self):
        global ADDR, addr, udp_server, file_trans, instant_camera, row, last_row, message_flag, last_message, last_time, history_fd, is_you_leave, is_yy_on
    
        try:
            while True:
                data = raw_input()
                if last_message != None:
                    sys.stdout.write('\33[22;1H')
                    sys.stdout.flush()
                    print_in_mid("Last message didn't reply, maybe lost.", isInfo = True)
                    last_message = None
                if data == "":
                    sys.stdout.write('\33[22;1H')
                    sys.stdout.flush()
                elif data != "@history" and data != "@h" and not addr:
                    sys.stdout.write("\33[22;1H\33[2K\33[23;1H\33[2K\33[24;1H\33[2K\33[22;1H")
                    sys.stdout.flush()
                    os.popen("zenity --title=PyChat --warning --text=无人在线！ 1>&- 2>&-")
                elif data == "@l" or data == "@leave":
                    sys.stdout.write("\33[22;1H\33[2K\33[23;1H\33[2K\33[24;1H\33[2K\33[22;1H")
                    sys.stdout.flush()
                    udp_server.sendto(b'\x11\x11\x11', addr)
                else:
                    if data != "@history" and data != "@h" and is_you_leave:
                        print_in_mid("Client left, may cannot reply immediately", isInfo = True)
                        
                    if data == "@history" or data == "@h":
                        sys.stdout.write("\33[22;1H\33[2K\33[23;1H\33[2K\33[24;1H\33[2K\33[22;1H")
                        sys.stdout.flush()
                        os.popen(cur_file_dir() + "/chatServer.py --history")
                    elif data == "@file" or data == "@f":
                        sys.stdout.write("\33[22;1H\33[2K\33[23;1H\33[2K\33[24;1H\33[2K\33[22;1H")
                        sys.stdout.flush()
                        paths = os.popen("zenity --title=PyChat-文件传输 --file-selection --multiple").read().strip("\n")
                        if paths != "":
                            thread.start_new_thread(file_trans.send_file, (paths, ))
                    elif data == "@i" or data == "@image":
                        sys.stdout.write("\33[22;1H\33[2K\33[23;1H\33[2K\33[24;1H\33[2K\33[22;1H")
                        sys.stdout.flush()
                        paths = os.popen("zenity --title=PyChat-图片传输 --file-selection --multiple --file-filter=\"BMP/JPG/JPEG/PNG/GIF|*.BMP *.bmp *.JPG *.jpg *.JPEG *.jpeg *.PNG *.png *.GIF *.gif\"").read().strip("\n")
                        if paths != "":
                            thread.start_new_thread(file_trans.send_image, (paths, ))
                    elif data == "@s" or data == "@screenshot":
                        sys.stdout.write("\33[22;1H\33[2K\33[23;1H\33[2K\33[24;1H\33[2K\33[22;1H")
                        sys.stdout.flush()
                        os.system("mkdir -p ~/Pictures/PyChat/ScreenShot")
                        paths = os.getenv("HOME") + "/Pictures/PyChat/ScreenShot/" + datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d %H:%M:%S') + ".png"
                        os.system("gnome-screenshot -a -f \"" + paths + "\" 1>&- 2>&-; sleep 1")
                        if os.path.exists(paths):
                            thread.start_new_thread(file_trans.send_image, (paths, ))
                    elif data == "@v" or data == "@video":
                        sys.stdout.write("\33[22;1H\33[2K\33[23;1H\33[2K\33[24;1H\33[2K\33[22;1H")
                        sys.stdout.flush()
                        if not instant_camera.started:
                            instant_camera.tostart = True
                    elif data == "@y" or data == "@yy":
                        sys.stdout.write("\33[22;1H\33[2K\33[23;1H\33[2K\33[24;1H\33[2K\33[22;1H")
                        sys.stdout.flush()
                        if is_yy_on:
                            os.system("pkill yyclient")
                            is_yy_on = False
                            print_in_mid("voice chat ended", isInfo = False)
                        else:
                            os.popen(os.environ["HOME"] + "/Apps/localchat/yyclient " + addr[0])
                            is_yy_on = True
                            print_in_mid("voice chat started", isInfo = False)
                        udp_server.sendto("@yy", addr)
                    else:
                        sys.stdout.write("\33[22;1H\33[2K\33[23;1H\33[2K\33[24;1H\33[2K\33[22;1H")
                        sys.stdout.flush()
                        
                        data = data.replace("\t", "")
                        if data == "":
                            continue
                        else:
                            last_message = message_flag
                            message_flag += 1
                        
                        if (datetime.datetime.now() - last_time).seconds > 300:
                            last_time = datetime.datetime.now()
                            print_in_mid(datetime.datetime.strftime(last_time, '%Y-%m-%d %H:%M:%S'))
                    
                        aes = AES.new(b'fuck your ass!??', AES.MODE_CBC, b'who is daddy!!??')
                        try: ##
                            udp_server.sendto(aes.encrypt('\0' + str(last_message) + '\0' + data + '\0' * (16 - (len(data) + 2 + len(str(last_message))) % 16)), addr)
                        except:
                            last_message = None
                            message_flag -= 1
                            continue
                        
                        sys.stdout.write('\33[' + str(row) + ';1H' + wrap(data, False) + '\n\33[22;1H')
                        sys.stdout.flush()
                        history_fd.write(">" + data + "\n")
                        row = row + last_row
                        if row > 20:
                            row = 20
        except Exception, e:
            os.system("zenity --error --text=\"" + str(e) + "\n" + traceback.format_exc() + "\"")
            sys.exit(1)

class FileTrans(threading.Thread):
    def run(self):
        global tcp_server

        try:
            while True:
                while True:
                    try:
                        tcpconn, tcpaddr = tcp_server.accept()
                    except:
                        continue
                    break
                try:
                    data = tcpconn.recv(BUFSIZE)
                except:
                    os.popen("zenity --error --text=\"" + "文件传输请求超时" + "\"")
                    tcpconn.close()
                    continue
                if data[0] == "\xFF":
                    name_sizes = data[1:].split("||")
                    for i in range(len(name_sizes)):
                        name_sizes[i] = name_sizes[i].split("|")
                    command = "zenity --title=PyChat --width=600 --height=400 --list --checklist --multiple --text=文件传输请求 --column=\"\" --column=序号 --column=文件名 --column=文件大小 "
                    i = 1
                    for name_size in name_sizes:
                        command += "TRUE " + str(i) + " \"" + name_size[0] + "\" " + self.sizefbyte(int(name_size[1]))
                        i += 1
                    selections = os.popen(command).read().strip("\n")
                    if selections == "":
                        tcpconn.close()
                        continue
                    save_dir = os.popen("zenity --title=文件保存目录 --file-selection --directory").read().strip("\n")
                    if save_dir == "":
                        tcpconn.close()
                        continue
                    try:
                        tcpconn.sendall(selections)
                    except Exception, e:
                        os.popen("zenity --error --text=\"" + str(e) + "\"")
                        tcpconn.close()
                        continue
                    progress = subprocess.Popen("zenity --title=PyChat --progress --text=\"waiting...\" --auto-close", shell = True, stdin = subprocess.PIPE)
                    total_size = 0
                    now_size = 0
                    for selection in selections.split("|"):
                        total_size += int(name_sizes[int(selection) - 1][1])
                    for selection in selections.split("|"):
                        name_size = name_sizes[int(selection) - 1]
                        while os.path.exists(save_dir + "/" + name_size[0]):
                            name_size[0] = "new_" + name_size[0]
                        name_size[1] = int(name_size[1])
                        if progress.poll() == None:
                            progress.stdin.write("#" + name_size[0] + "\n")
                            progress.stdin.flush()
                            save_fd = open(save_dir + "/" + name_size[0], "wb")
                            while name_size[1] > BUFSIZE:
                                if progress.poll() != None:
                                    break
                                data = ""
                                while len(data) != BUFSIZE:
                                    try:
                                        data_temp = tcpconn.recv(BUFSIZE - len(data))
                                    except:
                                        data = ""
                                        break
                                    if data_temp == "":
                                        data = ""
                                        break
                                    else:
                                        data += data_temp
                                if data == "":
                                    os.popen("zenity --error --text=\"传送失败: " + name_size[0] + "\"")
                                    progress.kill()
                                save_fd.write(data)
                                name_size[1] -= BUFSIZE
                                now_size += BUFSIZE
                                if progress.poll() == None:
                                    try: ## simulate atomic operation
                                        progress.stdin.write(str(100 - int(math.ceil((total_size - now_size) * 100.0 / total_size))) + "\n")
                                        progress.stdin.flush()
                                    except:
                                        progress.wait()
                                        break
                                else:
                                    break
                            if progress.poll() == None:
                                data = ""
                                while len(data) != name_size[1]:
                                    try:
                                        data_temp = tcpconn.recv(name_size[1] - len(data))
                                    except:
                                        data = ""
                                        break
                                    if data_temp == "":
                                        data = ""
                                        break
                                    else:
                                        data += data_temp
                                if data == "":
                                    os.popen("zenity --error --text=\"传送失败: " + name_size[0] + "\"")
                                    progress.kill()
                                save_fd.write(data)
                                now_size += name_size[1]
                                if progress.poll() == None:
                                    try: ## simulate atomic operation
                                        progress.stdin.write(str(100 - int(math.ceil((total_size - now_size) * 100.0 / total_size))) + "\n")
                                        progress.stdin.flush()
                                    except:
                                        progress.wait()
                        if progress.poll() == None or progress.poll() == 0:
                            save_fd.flush()
                            save_fd.close()
                            if name_size[0] == "update.zip":
                                os.popen("unzip -o " + save_dir + "/update.zip -d " + os.environ["HOME"] + "/Apps/localchat/")
                                os.popen("zenity --info --text=PyChat更新完毕，稍后请重新启动")
                        else:
                            save_fd.close()
                            os.popen("rm -f \"" + save_dir + "/" + name_size[0] + "\"")
                            break
                elif data[0] == "\xEE":
                    name_sizes = data[1:].split("||")
                    for i in range(len(name_sizes)):
                        name_sizes[i] = name_sizes[i].split("|")
                    command = "zenity --title=PyChat --width=600 --height=400 --list --checklist --multiple --text=图片传输请求 --column=\"\" --column=序号 --column=文件名 "
                    i = 1
                    for name_size in name_sizes:
                        command += "TRUE " + str(i) + " \"" + name_size[0] + "\" "
                        i += 1
                    selections = os.popen(command).read().strip("\n")
                    if selections == "":
                        tcpconn.close()
                        continue
                    os.system("mkdir -p ~/Pictures/PyChat")
                    save_dir = os.getenv("HOME") + "/Pictures/PyChat"
                    if save_dir == "":
                        tcpconn.close()
                        continue
                    try:
                        tcpconn.sendall(selections)
                    except Exception, e:
                        os.popen("zenity --error --text=\"" + str(e) + "\"")
                        tcpconn.close()
                        continue
                    for selection in selections.split("|"):
                        name_size = name_sizes[int(selection) - 1]
                        while os.path.exists(save_dir + "/" + name_size[0]):
                            name_size[0] = "new_" + name_size[0]
                        name_size[1] = int(name_size[1])
                        save_fd = open(save_dir + "/" + name_size[0], "wb")
                        while name_size[1] > BUFSIZE:
                            data = ""
                            while len(data) != BUFSIZE:
                                try:
                                    data_temp = tcpconn.recv(BUFSIZE - len(data))
                                except:
                                    data = ""
                                    break
                                if data_temp == "":
                                    data = ""
                                    break
                                else:
                                    data += data_temp
                            if data == "":
                                os.popen("zenity --error --text=\"传送失败: " + name_size[0] + "\"")
                                data = None
                                break
                            save_fd.write(data)
                            name_size[1] -= BUFSIZE
                        if not data:
                            save_fd.close()
                            os.popen("rm -f \"" + save_dir + "/" + name_size[0] + "\"")
                            break
                        data = ""
                        while len(data) != name_size[1]:
                            try:
                                data_temp = tcpconn.recv(name_size[1] - len(data))
                            except:
                                data = ""
                                break
                            if data_temp == "":
                                data = ""
                                break
                            else:
                                data += data_temp
                        if data == "":
                            os.popen("zenity --error --text=\"传送失败: " + name_size[0] + "\"")
                            save_fd.close()
                            os.popen("rm -f \"" + save_dir + "/" + name_size[0] + "\"")
                            break
                        save_fd.write(data)
                        save_fd.flush()
                        save_fd.close()
                        os.popen("xdg-open \"" + save_dir + "/" + name_size[0] + "\" 1>&- 2>&-")
                tcpconn.close()
        except Exception, e:
            os.system("zenity --error --text=\"" + str(e) + "\n" + traceback.format_exc() + "\"")
            sys.exit(1)
                    
    
    def send_file(self, paths):
        global addr, PORT

        files = paths.split("|")
        tcp_client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_client.connect((addr[0], PORT + 2))
        data = ""
        for f in files:
            data += f[f.rfind("/") + 1:] + "|"
            data += str(os.path.getsize(f)) + "||"
        try:
            tcp_client.sendall("\xFF" + data[:-2])
        except Exception, e:
            os.popen("zenity --error --text=\"" + str(e) + "\"")
            tcp_client.close()
            return
        try:
            selections = tcp_client.recv(BUFSIZE)
        except:
            os.popen("zenity --error --text=\"" + "文件传输请求超时" + "\"")
            tcp_client.close()
            return
        if selections == "":
            tcp_client.close()
            return
        for selection in selections.split("|"):
            try:
                tcp_client.sendall(open(files[int(selection) - 1]).read())
            except Exception, e:
                os.popen("zenity --error --text=\"传送失败: " + files[int(selection) - 1] + "\"")
                tcp_client.close()
                return
        tcp_client.close()
        print_in_mid("file transfer finished", isInfo = True)
    
    def send_image(self, paths):
        global addr, PORT

        files = paths.split("|")
        tcp_client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_client.connect((addr[0], PORT + 2))
        data = ""
        for f in files:
            data += f[f.rfind("/") + 1:] + "|"
            data += str(os.path.getsize(f)) + "||"
        try:
            tcp_client.sendall("\xEE" + data[:-2])
        except Exception, e:
            os.popen("zenity --error --text=\"" + str(e) + "\"")
            tcp_client.close()
            return
        try:
            selections = tcp_client.recv(BUFSIZE)
        except:
            os.popen("zenity --error --text=\"" + "文件传输请求超时" + "\"")
            tcp_client.close()
            return
        if selections == "":
            tcp_client.close()
            return
        for selection in selections.split("|"):
            try:
                tcp_client.sendall(open(files[int(selection) - 1]).read())
            except Exception, e:
                os.popen("zenity --error --text=\"传送失败: " + files[int(selection) - 1] + "\"")
                tcp_client.close()
                return
        tcp_client.close()
        print_in_mid("image transfer finished", isInfo = True)
    
    def sizefbyte(self, byte_count):
        if byte_count / 1024 == 0:
            return "{0:d}\\ B ".format(byte_count)
        elif byte_count / (1024 * 1024) == 0:
            return "{0:.1f}\\ KB ".format(byte_count / 1024.0)
        elif byte_count / (1024 ** 3) == 0:
            return "{0:.1f}\\ MB ".format(byte_count / (1024.0 * 1024.0))
        else:
            return "{0:.1f}\\ GB ".format(byte_count / (1024.0 ** 3))

class InstVideo(threading.Thread):
    surface_buffer = ""
    new_surface = None
    video_surface = None
    
    started = False
    
    def __init__(self):
        threading.Thread.__init__(self)
        pygame.display.init()
    
    def __del__(self):
        pygame.display.quit()
    
    def run(self):
        global video_server, instant_camera
        
        try:
            while True:
                count = 0
                while True:
                    try:
                        tcpconn, tcpaddr = video_server.accept()
                    except:
                        continue
                    break
                data = ""
                while len(data) != BUFSIZE:
                    try:
                        data_temp = tcpconn.recv(BUFSIZE - len(data))
                    except:
                        data = ""
                        break
                    if data_temp == "":
                        data = ""
                        break
                    else:
                        data += data_temp
                if not self.started and data[:4] == "@beg":
                    self.surface_buffer = ""
                    self.new_surface = None
                    self.video_surface = None
                    self.started = True
                    
                    if not instant_camera.started:
                        instant_camera.tostart = True
                    
                    pygame.display.init()
                    pygame.display.set_caption("PyChat")
                    pygame.display.set_icon(pygame.image.load("/usr/share/icons/hicolor/256x256/apps/cheese.png"))
                    self.video_surface = pygame.display.set_mode((320, 240), 0, 24)
                    self.surface_buffer += data[4:]
                    count += BUFSIZE - 4
                    running = True
                    while running:
                        data = ""
                        while len(data) != BUFSIZE:
                            try:
                                data_temp = tcpconn.recv(BUFSIZE - len(data))
                            except:
                                data = ""
                                break
                            if data_temp == "":
                                data = ""
                                break
                            else:
                                data += data_temp
                        if data == "" or data[:4] == "@end":
                            break
                        if 230400 - count >= BUFSIZE:
                            self.surface_buffer += data
                            count += BUFSIZE
                        else:
                            self.surface_buffer += data[:230400 - count]
                            count = 0
                            self.new_surface = pygame.image.fromstring(self.surface_buffer, (320, 240), "RGB")
                            self.surface_buffer = ""
                            self.video_surface.blit(self.new_surface, (0, 0))
                            pygame.display.update()
                        for event in pygame.event.get():
                            if event.type == pygame.QUIT:
                                running = False
                                break
                    pygame.display.quit()
                    self.surface_buffer = ""
                    self.new_surface = None
                    self.video_surface = None
                    self.started = False
                tcpconn.close()
                instant_camera.toend = True
        except Exception, e:
            os.system("zenity --error --text=\"" + str(e) + "\n" + traceback.format_exc() + "\"")
            sys.exit(1)

class InstCamera(threading.Thread):
    cam = None
    
    started = False
    tostart = False
    toend = False
    
    def __init__(self):
        threading.Thread.__init__(self)
        pygame.camera.init()
        self.cam = pygame.camera.Camera(pygame.camera.list_cameras()[0], (320, 240), "RGB")
    
    def __del__(self):
        if self.cam and self.started:
            try:
                self.cam.stop()
            except:
                pass
        pygame.camera.quit()
    
    def run(self):
        try:
            while True:
                if not self.started and not self.tostart:
                    time.sleep(0.25)
                elif not self.started and self.tostart:
                    self.cam.start()
                    self.started = True
                    self.tostart = False
                elif self.started and not self.toend:
                    cam_client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    cam_client.connect((addr[0], PORT - 2))
                    try:
                        cam_client.sendall("@beg" + pygame.image.tostring(self.cam.get_image(), "RGB") + '\0' * (BUFSIZE - (230400 + 4) % BUFSIZE))
                        time.sleep(0.25)
                        while not self.toend:
                            cam_client.sendall(pygame.image.tostring(self.cam.get_image(), "RGB") + '\0' * (BUFSIZE - 230400 % BUFSIZE))
                            time.sleep(0.25)
                    except:
                        self.toend = True
                elif self.started and self.toend:
                    try:
                        cam_client.sendall("@end" + '\0' * (BUFSIZE - 4))
                    except:
                        pass
                    cam_client.close()
                    self.cam.stop()
                    self.started = False
                    self.tostart = False
                    self.toend = False
                else:
                    self.started = False
                    self.tostart = False
                    self.toend = False
        except Exception, e:
            os.system("zenity --error --text=\"" + str(e) + "\n" + traceback.format_exc() + "\"")
            sys.exit(1)

class MessageNotifier(threading.Thread):
    count = 0
    
    def run(self):
        global window_id, message_count, message_sound
        
        while True:
            if int(os.popen("xdotool getwindowfocus").read().strip("\n")) != window_id:
                if self.count > 30 and message_count > 0:
                    os.popen("~/Apps/bin/notify-request PyChat \"" + str(message_count) + " unread messages" + "\" /usr/share/icons/hicolor/256x256/apps/cheese.png")
                    message_sound.play()
                    self.count = 0
            else:
                message_count = 0
                self.count = 0
            
            if message_count > 0:
                self.count += 1
            time.sleep(1)

def main(argv):
    global HOST, ADDR, addr, udp_server, tcp_server, video_server, file_trans, instant_camera, row, last_time, last_heart_beat, history_fd, window_id, message_sound
    
    errlog = open("/dev/null", "w")
    sys.stderr = errlog
    
#    HOST = get_public_addr()
    HOST = "0.0.0.0"
    ADDR = (HOST, PORT)
    
    history_fd = open(os.getenv("HOME") + "/.chat_history.dat", "a+")
    
    if len(argv) > 0:
        if argv[0] == "--history":
            history_temp_file = tempfile.NamedTemporaryFile(bufsize = 4096)
            history_fd.seek(0,0)
            for line in history_fd.readlines():
                if line[0] == "<":
                    history_temp_file.write('\33[1G\33[34m' + wrap(line[1:].rstrip("\n"), True) + '\33[0m\n')
                elif line[0] == ">":
                    history_temp_file.write('\33[1G' + wrap(line[1:].rstrip("\n"), False) + '\n')
                elif line[0] == "@":
                    history_temp_file.write('\33[' + str(40 - len(line) / 2 + 1) + 'G\33[33m' + line[1:] + '\33[0m\n')
                else:
                    print "\33[31m历史记录文件损坏！\33[0m\n"
                    history_temp_file.close()
                    history_fd.close()
                    raw_input("回车键退出。。。")
                    exit(1)
            history_temp_file.flush()
            os.popen("gnome-terminal -e 'less -r +G \"" + history_temp_file.name + "\"' --hide-menubar --geometry=80x24 --title=历史记录")
            time.sleep(3)
            history_temp_file.close()
            history_fd.close()
            sys.exit(0)
    
    signal.signal(signal.SIGINT, sig_hdr)
    signal.signal(signal.SIGQUIT, sig_hdr)
    signal.signal(signal.SIGTERM, sig_hdr)

    signal.signal(signal.SIGUSR1, sig_usr1_hdr)
    
    ## !experiment!
    window_id = int(os.popen("wmctrl -l -p | grep PyChat | (read id var2; echo $id)").read().strip("\n"), 16)
    
    # gtk is not compatible with daemon
    os.system(os.getenv("HOME") + "/Apps/localchat/init_window.py " + str(window_id))
    
    pygame.mixer.init()
    message_sound = pygame.mixer.Sound(os.environ["HOME"] + "/Apps/localchat/msg.wav")
    
    os.system("if [ \"$(pactl list | grep module-echo-cancel)\" = \"\" ]; then pactl load-module module-echo-cancel aec_method=\\\"speex\\\" >&- 2>&-; fi")
    os.system(os.environ["HOME"] + "/Apps/localchat/yyserver &")
    ## !experiment!
    
    udp_server.bind(ADDR)
    
    tcp_server.bind((ADDR[0], PORT + 1))
    tcp_server.listen(10)
    tcp_server.settimeout(10)
    
    video_server.bind((ADDR[0], PORT - 1))
    video_server.listen(1)
    video_server.settimeout(10)

    last_time = datetime.datetime.now()
    
    sys.stdout.write('\33[2J\33[1;20r\33[21;1H--------------------------------------------------------------------------------\33[22;1H')
    sys.stdout.flush()
    print_in_mid(datetime.datetime.strftime(last_time, '%Y-%m-%d %H:%M:%S'))
    
    tMsg = TMsg()
    tInput = TInput()
    file_trans = FileTrans()
    instant_video = InstVideo()
    instant_camera = InstCamera()
    message_notifier = MessageNotifier()
    tMsg.setDaemon(True)
    tInput.setDaemon(True)
    file_trans.setDaemon(True)
    instant_video.setDaemon(True)
    instant_camera.setDaemon(True)
    message_notifier.setDaemon(True)
    tMsg.start()
    tInput.start()
    file_trans.start()
    instant_video.start()
    instant_camera.start()
    message_notifier.start()
    while tMsg.isAlive() and tInput.isAlive() and file_trans.isAlive() and instant_video.isAlive() and instant_camera.isAlive() and message_notifier.isAlive():
        if addr and last_heart_beat and (datetime.datetime.now() - last_heart_beat).seconds > 30:
            print_in_mid("IP: " + addr[0] + " disconnected!", isInfo = True)
            last_heart_beat = None
            # xdotool getactivewindow uses _NET_ACTIVE_WINDOW from the EWMH spec,
            # which is not supported well on Fedora.
            # see xdotool[https://github.com/jordansissel/xdotool/blob/master/xdo.h]
            if int(os.popen("xdotool getwindowfocus").read().strip("\n")) != window_id:
                os.popen("~/Apps/bin/notify-request PyChat \"IP: " + addr[0] + " disconnected!\" /usr/share/icons/hicolor/256x256/apps/cheese.png")
                message_sound.play()
        time.sleep(1)

if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except Exception, e:
        os.system("zenity --error --text=\"" + str(e) + "\n" + traceback.format_exc() + "\"")
        sys.exit(1)
