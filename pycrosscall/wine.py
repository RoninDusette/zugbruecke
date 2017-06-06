# -*- coding: utf-8 -*-


# +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
# IMPORT
# +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

import os
import signal
import subprocess
import sys
import threading
import time
import xmlrpc.client

from .lib import get_location_of_file


# +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
# WINE SESSION CLASS
# +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

class wine_session_class:


	# session init
	def __init__(self, session_id, parameter, session_log):

		# Set ID, parameters and pointer to log
		self.id = session_id
		self.p = parameter
		self.log = session_log

		# Log status
		self.log.out('wine session starting ...')

		# Fire session up
		self.__session_start__()

		# Log status
		self.log.out('wine session started')


	# flow control routine for setting things up, called once from init
	def __session_start__(self):

		# Session is up
		self.up = True

		# Get location of this script file
		self.dir_thisfile = get_location_of_file(__file__)

		# Set environment variables for wine
		self.__set_wine_env__()

		# Translate this file's Unix path into Wine path
		self.dir_thisfile_wine = self.translate_path_unix2win(self.dir_thisfile)

		# Start wine server
		self.__wine_server_start__()

		# Start wine python
		self.__wine_python_start__(self.__compile_wine_python_command__())


	# session destructor
	def terminate(self):

		if self.up:

			# Log status
			self.log.out('wine session terminating ...')

			# Shut down wine python
			self.__wine_python_stop__()

			# Stop wine server
			self.__wine_server_stop__()

			# Log status
			self.log.out('wine session terminated')

			# Session is down
			self.up = False


	def __set_wine_env__(self):

		# Change the environment for Wine: Architecture
		os.environ['WINEARCH'] = self.p['arch']

		# Change the environment for Wine: Wine prefix / profile directory
		os.environ['WINEPREFIX'] = os.path.join(self.dir_thisfile, self.p['arch'] + '-wine')


	def __wine_server_start__(self):

		# Start wine server into prepared environment
		self.proc_wineserver = subprocess.Popen(
			['wineserver', '-f', '-p'], # run persistent in foreground
			stdin = subprocess.PIPE,
			stdout = subprocess.PIPE,
			stderr = subprocess.PIPE,
			shell = False
			)

		# Status log
		self.log.out('wineserver started with PID %d' % self.proc_wineserver.pid)

		# HACK wait due to lack of feedback
		time.sleep(1) # seconds


	def __compile_wine_python_command__(self):

		# Python interpreter's directory seen from this script
		self.dir_python = os.path.join(self.dir_thisfile, self.p['arch'] + '-python' + self.p['version'])

		# Identify wine command for 32 or 64 bit
		if self.p['arch'] == 'win32':
			wine_cmd = 'wine'
		elif self.p['arch'] == 'win64':
			wine_cmd = 'wine64'
		else:
			raise # TODO error

		# Prepare Wine-Python server command with session id and return it
		return [
			wine_cmd,
			os.path.join(self.dir_python, 'python.exe'),
			"%s\\wine_server.py" % self.dir_thisfile_wine,
			'--id', self.id,
			'--port_in', str(self.p['port_wine']),
			'--port_out', str(self.p['port_unix'])
			]


	def __read_output_from_pipe__(self, pipe, func):

		for line in iter(pipe.readline, b''):
			func('[P] ' + line.decode('utf-8'))
		pipe.close()


	def __wine_python_start__(self, command_list):

		# Log status
		self.log.out('wine-python command: ' + ' '.join(command_list))

		# Fire up Wine-Python process
		self.proc_winepython = subprocess.Popen(
			command_list,
			stdin = subprocess.PIPE,
			stdout = subprocess.PIPE,
			stderr = subprocess.PIPE,
			shell = False,
			preexec_fn = os.setsid,
			close_fds = True,
			bufsize = 1
			)

		# Status log
		self.log.out('wine-python started with PID %d' % self.proc_winepython.pid)

		# Prepare threads for stdout and stderr capturing of Wine
		# BUG does not capture stdout from windows binaries (running with Wine) most of the time
		self.thread_winepython_out = threading.Thread(
			target = self.__read_output_from_pipe__,
			args = (self.proc_winepython.stdout, self.log.out),
			name = 'out'
			)
		self.thread_winepython_err = threading.Thread(
			target = self.__read_output_from_pipe__,
			args = (self.proc_winepython.stderr, self.log.err),
			name = 'err'
			)

		# Start threads
		for t in (self.thread_winepython_out, self.thread_winepython_err):
			t.daemon = True
			t.start()

		# HACK Wait ...
		time.sleep(1) # seconds

		# Log status
		self.log.out('threads for wine-python logging started')

		# Fire up xmlrpc client
		self.client = xmlrpc.client.ServerProxy('http://localhost:8000')

		# Log status
		self.log.out('xmlrpc client started')


	def __wine_python_stop__(self):

		print(0)

		# Tell server via message to terminate
		self.client.terminate()

		print(1)

		# Terminate Wine-Python
		os.killpg(os.getpgid(self.proc_winepython.pid), signal.SIGINT)

		print(2)

		for t_index, t in enumerate([self.thread_winepython_out, self.thread_winepython_err]):
			self.log.out('joining thread "%s" ...' % t.name)
			t.join(timeout = 1) # seconds

		print(3)

		# HACK wait for its destructor
		time.sleep(1) # seconds

		print(4)


	def __wine_server_stop__(self):

		print(5)

		# Killing the server requires two signals as specified in the man page
		os.kill(self.proc_wineserver.pid, signal.SIGINT)
		print(6)
		os.kill(self.proc_wineserver.pid, signal.SIGKILL)
		# os.killpg(os.getpgid(self.proc_wineserver.pid), signal.SIGINT)
		# os.killpg(os.getpgid(self.proc_wineserver.pid), signal.SIGKILL)

		print(7)


	def translate_path_unix2win(self, path):

		# Start winepath for tanslating path, catch output from all pipes
		winepath_p = subprocess.Popen(
			['winepath', '-w', path],
			stdin = subprocess.PIPE,
			stdout = subprocess.PIPE,
			stderr = subprocess.PIPE
			)

		# Get stdout and stderr
		wine_out, wine_err = winepath_p.communicate()

		# Pass stderr into log
		self.log.err(wine_err.decode(encoding = 'UTF-8'))

		# Return translated path
		return wine_out.decode(encoding = 'UTF-8').strip()
