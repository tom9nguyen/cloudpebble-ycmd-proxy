#!/usr/bin/env python
import gevent.monkey; gevent.monkey.patch_all(subprocess=True)
from flask import Flask, request, jsonify
from flask.ext.cors import cross_origin
import uuid
import tempfile
import os
import os.path
import errno
import atexit
import gevent

import settings
from ycm import YCM

app = Flask(__name__)

mapping = {}

@app.route('/spinup', methods=['POST'])
def spinup():
    content = request.get_json(force=True)
    root_dir = tempfile.mkdtemp()
    print root_dir
    # Dump all the files we should need.
    for path, content in content['files'].iteritems():
        abs_path = os.path.normpath(os.path.join(root_dir, path))
        if not abs_path.startswith(root_dir):
            raise Exception("Failed: escaped root directory.")
        dir_name = os.path.dirname(abs_path)
        try:
            os.makedirs(dir_name)
        except OSError as e:
            if e.errno == errno.EEXIST and os.path.isdir(dir_name):
                pass
            else:
                raise
        with open(abs_path, 'w') as f:
            f.write(content)

    settings_path = os.path.join(root_dir, ".ycm_extra_conf.py")
    with open(settings_path, "w") as f:
        f.write("""
import os

def FlagsForFile(filename, **kwargs):
    return {{
        'flags': [
            '-std=c11',
            '-x',
            'c',
            '-Wall',
            '-Wextra',
            '-Werror',
            '-Wno-unused-parameter',
            '-Wno-error=unused-function',
            '-Wno-error=unused-variable',
            '-I{sdk}/Pebble/include',
            '-I{here}/build',
            '-I{here}',
            '-I{here}/build/src',
            '-I{here}/src',
            '-I{stdlib}',
            '-DRELEASE',
        ],
        'do_cache': True,
    }}
""".format(sdk=settings.PEBBLE_SDK, here=root_dir, stdlib=settings.STDLIB_INCLUDE_PATH))

    ycm = YCM(root_dir)
    ycm.wait()
    ycm.apply_settings(settings_path)

    # Keep track of it
    this_uuid = str(uuid.uuid4())
    mapping[this_uuid] = YCM(root_dir)
    print mapping
    # victory!
    return jsonify(success=True, uuid=this_uuid)

@app.route('/ycm/<process_uuid>/completions', methods=['POST'])
@cross_origin(headers=["X-Requested-With","X-CSRFToken","Content-Type"])
def get_completions(process_uuid):
    if process_uuid not in mapping:
        return "Not found", 404
    ycm = mapping[process_uuid]
    data = request.get_json(force=True)
    if 'patches' in data:
        ycm.apply_patches(data['patches'])
    ycm.parse(data['file'], data['line'], data['ch'])
    return jsonify(completions=ycm.get_completions(data['file'], data['line'], data['ch']))


@atexit.register
def kill_completers():
    global mapping
    for ycm in mapping.itervalues():
        ycm.close()
    mapping = {}


def monitor_processes(mapping):
    while True:
        print "process sweep running"
        gevent.sleep(60)
        to_kill = []
        for uuid, ycm in mapping.iteritems():
            if not ycm.alive:
                ycm.close()
                to_kill.append(uuid)
        for uuid in to_kill:
            del mapping[uuid]
        print "process sweep collected %d instances" % len(to_kill)


if __name__ == '__main__':
    g = gevent.spawn(monitor_processes, mapping)
    atexit.register(lambda: g.kill())

    app.debug = settings.DEBUG
    app.run(settings.HOST, settings.PORT)
