#! /usr/bin/env python3

import shutil
import subprocess
import os
import fnmatch
import requests
import json
import time


SRC_FOLDER = 'project'
BUILD_FOLDER = 'build'
VIPER_FOLDER = BUILD_FOLDER + '/viper/'
VIPER_PORT = '9999'
VIPER_URL = f'http://localhost:{VIPER_PORT}'
Z3_PATH = '/workdir/z3/bin/z3'


class ConsoleColors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    BACKGROUND_BLACK = "\033[40m"
    BACKGROUND_RED = "\033[41m"
    BACKGROUND_GREEN = "\033[42m"
    BACKGROUND_YELLOW = "\033[43m"
    BACKGROUND_BLUE = "\033[44m"
    BACKGROUND_MAGENTA = "\033[45m"
    BACKGROUND_CYAN = "\033[46m"
    BACKGROUND_WHITE = "\033[47m"


def exec(cmd, **kwargs):
    subprocess.run(cmd, check=True, text=True, **kwargs)


class TestSet:
    def __init__(self, name, files):
        self.name = name
        self.files = files


def testfiles() -> list[TestSet]:
    sets = {}

    for root, dirnames, filenames in os.walk(BUILD_FOLDER + '/tests/'):
        for filename in fnmatch.filter(filenames, '*.spr'):
            filename = os.path.join(root, filename)
            if 'elective/' in filename:
                group = filename.split('elective/')[1].split('/')[0]
            elif '04-sheet' in filename:
                group = 'required'
            else:
                continue

            if group not in sets:
                sets[group] = TestSet(group, [])
            sets[group].files.append(filename)
            
    return list(sets.values())


def show(text, **kwargs):
    print(text, flush=True, **kwargs)


def fancy(text, top=True, bot=True):
    cols, _ = shutil.get_terminal_size()
    text = text.center(min(60, cols))
    line = '─' * (len(text) + 2)
    if top:
        show(f'╭{line}╮')
    show(f'│ {text} │')
    if bot:
        show(f'╰{line}╯')


def delete_files_with_extension(directory, extension):
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(extension):
                file_path = os.path.join(root, file)
                os.remove(file_path)


def build():
    exec(['ghc', '--version'])
    try:
        shutil.rmtree(BUILD_FOLDER)
    except:
        pass
    shutil.copytree(SRC_FOLDER, BUILD_FOLDER)

    # if there's build files copied in from the source, we want to get rid of them
    # they were most likely compiled on the host system and aren't compatible here
    delete_files_with_extension(BUILD_FOLDER, "hi")
    delete_files_with_extension(BUILD_FOLDER, "o")

    exec(['ghc', '-o', 'Main', '-W', 'Main.hs'], cwd=BUILD_FOLDER)
    fancy('Successfully built Project')


def start_viper_server():
    subprocess.Popen(['java', '-Xss100m', '-jar', 'backends/viperserver.jar', '--port', VIPER_PORT, '--logLevel', 'WARN'], env={"Z3_EXE":Z3_PATH}, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    show('launched viper server')

    timeout = 10
    start_time = time.time()
    while True:
        try:
            response = requests.head(VIPER_URL)
            if response.status_code < 500:
                break
        except requests.RequestException:
            pass  # Retry if there's a connection error
        if time.time() - start_time >= timeout:
            show(f"Timed out waiting for viper to respond.")
            exit(-1)
        time.sleep(0.1)

    show(f'viper up and running ({VIPER_URL})')


def stop_viper_server():
    r = requests.get(f"{VIPER_URL}/exit")
    show(r.text)


def dump_file(file_path):
    with open(file_path, 'r') as file:
        show(f'FILE {file_path}')
        for i, line in enumerate(file, start=1):
            show(f"{i:03d}: {line}", end='')


def lines(res):
    buf = ''
    for chunk in res.iter_content(chunk_size=8192):
        if chunk:
            buf += chunk.decode('utf-8')
        while '\n' in buf:
            i = buf.find('\n')
            yield buf[:i]
            buf = buf[i+1:]


class TestResult:
    def __init__(self, spr_file):
        self.spr_file = spr_file
        self.vpr_file = None
        self.exception = None
        self.encodingFail = False
        self.expectFail = '.fail' in spr_file
        self.passed = []
        self.failed = []

    def add_exception(self, e):
        self.exception = e

    def add_pass(self, test):
        self.passed.append(test)

    def add_fail(self, test):
        self.failed.append(test)

    def encoding_success(self, vpr_file):
        self.vpr_file = vpr_file

    def encoding_failure(self):
        self.encodingFail = True

    def is_success(self):
        if self.exception:
            return False
        success = len(self.passed) > 0 and len(self.failed) == 0
        return success != self.expectFail

    def __str__(self):
        e = ''
        if self.is_success():
            color = ConsoleColors.GREEN
        elif self.exception:
            color = ConsoleColors.RED
            e = f'except={self.exception}'
        else:
            color = ConsoleColors.YELLOW
        
        if self.encodingFail:
            e = 'failed to encode'

        file = os.path.basename(self.spr_file)
        p = f'pass={len(self.passed)}'
        f = f'fail={self.failed}'

        if self.encodingFail:
            return f'{color}{file:<35}{e}{ConsoleColors.RESET}'
        else:
            return f'{color}{file:<35}{p:<10}{f} {e}{ConsoleColors.RESET}'


def verify_with_viper(test):
    try:
        verify_file_inner(test.vpr_file, test)
    except Exception as e:
        show(f'unhandled exception: {e}')
        test.add_exception(e)


def verify_file_inner(file, result: TestResult):

    headers = {'Content-Type': 'application/json'}
    req = {
        'arg': f'silicon "{os.path.abspath(file)}"'
    }
    response = requests.post(
        f"{VIPER_URL}/verify",
        data=json.dumps(req),
        headers=headers,
        timeout=5
    )
    id = response.json()['id']
    response = requests.get(
        f"http://localhost:{VIPER_PORT}/verify/{id}",
        stream=True
    )

    ignored = [
        'copyright_report', 
        'ast_construction_result', 
        'program_outline', 
        'configuration_confirmation',
        'program_definitions',
        'verification_termination_message'
    ]
    MSG_BODY = 'msg_body'
    MSG_TYPE = 'msg_type'

    dumped_file = False

    for line in lines(response):
        consumed = False
        parsed = json.loads(line)

        if (MSG_TYPE not in parsed) or (MSG_BODY not in parsed):
            show(f'idk what to do here: {line}')
            continue

        if parsed[MSG_TYPE] in ignored:
            continue

        try:
            body = parsed[MSG_BODY]
            typ = parsed[MSG_TYPE]
            if typ == 'statistics':
                funcs = body['functions']
                #show(f'found {funcs} functions.')
                consumed = True
            elif typ == 'verification_result':
                details = body['details']
                kind = body['kind']
                status = body['status']
                if kind == 'for_entity':
                    entity = details['entity']['name']
                    if status == 'success':
                        result.add_pass(entity)
                    else:
                        if not result.expectFail:
                            if not dumped_file:
                                dumped_file = True
                                dump_file(file)
                            show(details)
                        result.add_fail(entity)
                    consumed = True
                elif kind == 'overall':
                    show(f'{file}: {status}')
                    consumed = True
            elif typ == 'warnings_during_parsing':
                if len(body) > 0:
                    show(f'warnings: {body}')
                consumed = True
            elif typ == 'internal_warning_message':
                if 'Could not resolve expression' in body['text']:
                    consumed = True
                    pass
                else:
                    show(f'warning: {body["text"]}')


        finally:
            if not consumed:
                show(f'weird stuff: {line}')


def encode_file(test: TestResult):
    try:
        vpr_file = os.path.join(VIPER_FOLDER, test.spr_file.replace('spr', 'vpr'))
        try:
            os.makedirs(os.path.dirname(vpr_file))
        except:
            pass
        exec([f'{BUILD_FOLDER}/Main', 'encode', test.spr_file, vpr_file])
        test.encoding_success(vpr_file)
    except Exception as e:
        test.encoding_failure()


def e2e_verify(spr_file):
    test = TestResult(spr_file)
    encode_file(test)
    if not test.encodingFail:
        verify_with_viper(test)
    return test


def verify_set(tests: TestSet):
    successes = 0
    fancy(tests.name, True, False)
    for spr_file in tests.files:
        result = e2e_verify(spr_file)
        show(result)
        if result.is_success():
            successes += 1
    fancy(f'{tests.name}: passed {successes}/{len(tests.files)} tests', False, True)


def verify():
    for test_set in testfiles():
        verify_set(test_set)


def main():
    fancy('starting test suite')
    build()
    try:
        start_viper_server()
        verify()
    finally:
        stop_viper_server()
    fancy('finished test suite')

if __name__ == '__main__':
    main()
