#Github pull reqest builder for Jenkins

import json
import os
import re
import urllib2
import urllib
import base64
import requests
import sys
import traceback
import platform
import codecs
from shutil import copy

#set Jenkins build description using submitDescription to mock browser behavior
http_proxy = ''
if('HTTP_PROXY' in os.environ):
    http_proxy = os.environ['HTTP_PROXY']
proxyDict = {'http': http_proxy, 'https': http_proxy}

branch = "v3"
pr_num = 0
workspace = "."
node_name = "mac"
remote_build = False

def set_jenkins_job_description(desc, url):
    req_data = urllib.urlencode({'description': desc})
    req = urllib2.Request(url + 'submitDescription', req_data)
    #print(os.environ['BUILD_URL'])
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    base64string = base64.encodestring(os.environ['JENKINS_ADMIN'] + ":" + os.environ['JENKINS_ADMIN_PW']).replace('\n', '')
    req.add_header("Authorization", "Basic " + base64string)
    try:
        urllib2.urlopen(req)
    except:
        traceback.print_exc()

def check_current_3rd_libs(branch):
    print("start backup old 3rd libs...")
    #get current_libs config
    backup_files = range(2)
    current_files = range(2)
    config_file_paths = ['external/config.json', 'templates/lua-template-runtime/runtime/config.json']

    for i, config_file_path in enumerate(config_file_paths):
        if not os.path.isfile(config_file_path):
            raise Exception("Could not find 'external/config.json'")

        with open(config_file_path) as data_file:
            data = json.load(data_file)

        current_3rd_libs_version = data["version"]
        filename = current_3rd_libs_version + '.zip'
        node_name = os.environ['NODE_NAME']
        backup_file = '../../../cocos-2dx-external/node/' + node_name + '/' + filename
        backup_files[i] = backup_file
        current_file = filename
        current_files[i] = current_file
        if os.path.isfile(backup_file):
            copy(backup_file, current_file)
    #run download-deps.py
    print("prepare to downloading ...")
    os.system('python download-deps.py -r no')
    #backup file
    for i, backup_file in enumerate(backup_files):
        current_file = current_files[i]
        copy(current_file, backup_file)

def patch_cpp_empty_test():
    modify_file = 'tests/cpp-empty-test/Classes/AppDelegate.cpp'
    data = codecs.open(modify_file, encoding='UTF-8').read()
    data = re.sub("director->setDisplayStats\(true\);", "director->setDisplayStats(true); director->getConsole()->listenOnTCP(5678);", data)
    codecs.open(modify_file, 'wb', encoding='UTF-8').write(data)

    #modify tests/cpp-empty-test/proj.android/AndroidManifest.xml to support Console
    modify_file = 'tests/cpp-empty-test/proj.android/AndroidManifest.xml'
    data = codecs.open(modify_file, encoding='UTF-8').read()
    data = re.sub('<uses-feature android:glEsVersion="0x00020000" />', '<uses-feature android:glEsVersion="0x00020000" /> <uses-permission android:name="android.permission.INTERNET"/>', data)
    codecs.open(modify_file, 'wb', encoding='UTF-8').write(data)

def add_symbol_link_for_android_project(projects):
    global workspace

    print "current dir is: " + workspace
    os.system("cd " + workspace)
    android_build_objs_dir = "android_build_objs"
    os.mkdir(android_build_objs_dir)

    print platform.system()
    if(platform.system() == 'Darwin'):
        for item in projects:
            cmd = "ln -s " + workspace + android_build_objs_dir + workspace + "/tests/" + item + "/proj.android/obj"
            os.system(cmd)
    elif(platform.system() == 'Windows'):
        for item in projects:
            p = item.replace("/", os.sep)
            cmd = "mklink /J " + workspace + os.sep + "tests" + os.sep + p + os.sep + "proj.android" + os.sep + "obj " + workspace + os.sep + android_build_objs_dir
            print cmd
            os.system(cmd)



def send_notifies_to_github():
    global branch
    global pr_num
    global workspace
    global node_name
    global remote_build
    
    # get payload from os env
    payload_str = os.environ['payload']
    payload_str = payload_str.decode('utf-8', 'ignore')
    #parse to json obj
    payload = json.loads(payload_str)

    #get pull number
    pr_num = payload['number']
    print 'pr_num:' + str(pr_num)

    #build for pull request action 'open' and 'synchronize', skip 'close'
    action = payload['action']
    print 'action: ' + action

    #pr = payload['pull_request']

    url = payload['html_url']
    print "url:" + url
    pr_desc = '<h3><a href=' + url + '> pr#' + str(pr_num) + ' is ' + action + '</a></h3>'

    #get statuses url
    statuses_url = payload['statuses_url']

    #get pr target branch
    branch = payload['branch']
    workspace = os.environ['WORKSPACE']
    node_name = os.environ['NODE_NAME']

    #set commit status to pending
    #target_url = os.environ['BUILD_URL']
    jenkins_url = os.environ['JENKINS_URL']
    job_name = os.environ['JOB_NAME'].split('/')[0]
    build_number = os.environ['BUILD_NUMBER']
    target_url = jenkins_url + 'job/' + job_name + '/' + build_number + '/'

    set_jenkins_job_description(pr_desc, target_url)

    data = {"state": "pending", "target_url": target_url, "context": "Jenkins CI", "description": "Build started..."}
    access_token = os.environ['GITHUB_ACCESS_TOKEN']
    Headers = {"Authorization": "token " + access_token}

    try:
        requests.post(statuses_url, data=json.dumps(data), headers=Headers, proxies=proxyDict)
    except:
        traceback.print_exc()

def syntronize_remote_pr():
    #reset path to workspace root
    os.system("cd " + os.environ['WORKSPACE'])
    #pull latest code
    os.system("git pull origin " + branch)
    os.system("git checkout " + branch)
    os.system("git branch -D pull" + str(pr_num))
    #clean workspace
    print "Before checkout: git clean -xdf -f"
    os.system("git clean -xdf -f")
    #fetch pull request to local repo
    git_fetch_pr = "git fetch origin pull/" + str(pr_num) + "/head"
    ret = os.system(git_fetch_pr)
    if(ret != 0):
        return(2)

    #checkout a new branch from v3 or v4-develop
    git_checkout = "git checkout -b " + "pull" + str(pr_num)
    os.system(git_checkout)
    #merge pull reqeust head
    p = os.popen('git merge --no-edit FETCH_HEAD')
    r = p.read()
    #check if merge fail
    if r.find('CONFLICT') > 0:
        print r
        return(3)

    # After checkout a new branch, clean workspace again
    print "After checkout: git clean -xdf -f"
    os.system("git clean -xdf -f")

    #update submodule
    git_update_submodule = "git submodule update --init --force"
    ret = os.system(git_update_submodule)
    if(ret != 0):
        return(2)

def gen_scripting_bindings():
    global branch
    # Generate binding glue codes
    if(branch == 'v3' or branch == 'v4-develop'):
        ret = os.system("python tools/jenkins-scripts/slave-scripts/gen_jsb.py")
    if(ret != 0):
        return(1)


def do_build_slaves():
    global branch
    global node_name

    jenkins_script_path = "tools" + os.sep + "jenkins-scripts" + os.sep + "slave-scripts" + os.sep

    if(branch == 'v3' or branch == 'v4-develop'):
        slave_build_scripts = ""
        if(node_name == 'android') or (node_name == 'android_bak'):
            # patch_cpp_empty_test()
            slave_build_scripts = jenkins_script_path + "android-build.sh"
        elif(node_name == 'win32' or node_name == 'win32_win7' or node_name == 'win32_bak'):
            if branch == 'v3':
                slave_build_scripts = jenkins_script_path + "win32-vs2012-build.bat"
            else:
                slave_build_scripts = jenkins_script_path + "win32-vs2013-build.bat"
        elif(node_name == 'windows-universal' or node_name == 'windows-universal_bak'):
            if branch == 'v3':
                slave_build_scripts = jenkins_script_path + "windows-universal-v3.bat"
            else:
                slave_build_scripts = jenkins_script_path + "windows-universal.bat"
        elif(node_name == 'ios_mac' or node_name == 'ios' or node_name == 'ios_bak'):
            slave_build_scripts = jenkins_script_path + "ios-build.sh"
        elif(node_name == 'mac' or node_name == 'mac_bak'):
            slave_build_scripts = jenkins_script_path + "mac-build.sh"
        elif(node_name == 'linux_centos' or node_name == 'linux' or node_name == 'linux_bak'):
            slave_build_scripts = jenkins_script_path + "linux-build.sh"

        ret = os.system(slave_build_scripts)

    #get build result
    print "build finished and return " + str(ret)
    return ret
            
def main():
    global pr_num
    global workspace
    global branch
    global node_name
    global remote_build
    #for local debugging purpose, you could uncomment this line
    # remote_build = os.environ['REMOTE_BUILD']

    if remote_build is True:
        send_notifies_to_github()

        #syntronize local git repository with remote and merge the PR
        syntronize_remote_pr()

        #copy check_current_3rd_libs
        check_current_3rd_libs(branch)

        #generate jsb and luabindings
        gen_scripting_bindings()

    #add symbol link
    add_symbol_link_projects = ["cpp-empty-test", "cpp-tests"]
    add_symbol_link_for_android_project(add_symbol_link_projects)

    #start build jobs on each slave
    ret = do_build_slaves()

    exit_code = 1
    if ret == 0:
        exit_code = 0
    else:
        exit_code = 1

    #clean workspace
    if remote_build is True:
        os.system("cd " + workspace)
        os.system("git reset --hard")
        os.system("git clean -xdf -f")
        os.system("git checkout " + branch)
        os.system("git branch -D pull" + str(pr_num))
    else:
        print "local build, no need to cleanup"

    return(exit_code)

# -------------- main --------------
if __name__ == '__main__':
    sys_ret = 0
    try:
        sys_ret = main()
    except:
        traceback.print_exc()
        sys_ret = 1
    finally:
        sys.exit(sys_ret)
