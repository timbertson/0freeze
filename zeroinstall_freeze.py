#!/usr/bin/env python
from __future__ import print_function
import optparse
import subprocess
import os
import sys
import re
import logging
import urllib
import itertools
from version import Version, VersionComponent
from xdg import BaseDirectory
from xml.dom import minidom
from xml import dom

logging.basicConfig(level = logging.INFO)

from zeroinstall.injector import reader, namespaces
from zeroinstall.support import basedir

logger = logging.getLogger()

def filter_one(f, l, desc="match"):
	matches = list(filter(f, l))
	assert len(matches) == 1, "expected one %s, got %s" % (desc,len(matches))
	return matches[0]

def get_local_feed_file(url):
	if os.path.isabs(url):
		logging.debug("local feed: %s" % (url,))
		return url
	else:
		cached = basedir.load_first_cache(namespaces.config_site, 'interfaces', reader.escape(url))
		if not cached:
			raise RuntimeError("not cached")
		logging.debug("cached feed: %s" % (cached,))
		return cached

def clean_unused_commands(feed, command):
	all_commands = feed.getElementsByTagName("command")
	should_keep = lambda x: x.getAttribute("name") == command
	keep = list(filter(should_keep, all_commands))

	for cmd in all_commands[:]:
		if cmd not in keep:
			logger.debug("removing command name=%s" % (cmd.getAttribute("name")))
			cmd.parentNode.removeChild(cmd)
	
	for cmd in keep:
		cmd.setAttribute("name", "run")

def clean_feed(feed, command):
	for e in feed.childNodes[:]:
		if e.nodeType != dom.Node.ELEMENT_NODE: continue
		#TODO: check exhaustiveness
		if e.tagName in ['name', 'summary', 'group', 'requires', 'command', 'interface']: continue
		logging.debug("Cleanup: remove %s" % (e.tagName))
		feed.removeChild(e)
	
	clean_unused_commands(feed, command)

def isolate_implementation(feed, impl_id):
	# get active implementation, and delete all others:
	all_impls = feed.getElementsByTagName("implementation")
	is_selected_impl = lambda x: x.getAttribute("id") == impl_id
	active_impl = filter_one(is_selected_impl, all_impls, "impl_id=%s" % impl_id)
	logging.debug("found feed impl with id: %s" % (impl_id,))

	for impl in all_impls[:]:
		if impl is not active_impl:
			logger.debug("removing impl with id: %s" % (impl.getAttribute("id")))
			impl.parentNode.removeChild(impl)
	
	for group in feed.getElementsByTagName('group')[:]:
		if len(group.getElementsByTagName('implementation')) == 0:
			group.parentNode.removeChild(group)
	
	return active_impl

def main():
	p = optparse.OptionParser(usage='%prog [OPTIONS] input [output]')
	p.add_option('-r', '--refresh', action='store_true')
	p.add_option('-v', '--verbose', action='store_true')
	p.add_option('-o', '--offline', action='store_true')
	p.add_option('--components', type='int', help="lock down NUM version components. If NUM is positive, it locks down NUM leading components. "
			"If NUM is negative, it locks down all but NUM trailing components. The default value is -1.\n"
			"EXAMPLES:\n"
			"    --components=2 will lock down foo@1.2.3 to >=1.2.3<1.3.0.\n"
			"    --components=-2 will lock down foo@1.2.3 to >=1.2.3<1.3.0.\n"
			"This option is ignored if --exact is used", default=-1)
	p.add_option('--exact', action='store_true', help='use exact version (takes precedence over --components)')
	p.add_option('--ignore', action='append', dest='ignore', default=[], metavar='URL', help="Don't restrict interface URL")
	p.add_option('--allow-local', action='append', dest='nonlocal', default=[], metavar='URL', help="Allow URL to be satisfied by a local feed")
	p.add_option('-c', '--command', default='run')
	opts, args = p.parse_args()
	logger.setLevel(level=logging.DEBUG if opts.verbose else logging.INFO)
	input_file = args.pop(0)
	output_file = None
	if len(args) > 0:
		assert len(args) == 1, 'too many arguments'
		output_file, = args

	assert opts.components != 0, "components must not be 0"
	
	cmd = ['0install', 'select', '--console', '--xml', input_file]
	def add_flag(arg):
		cmd.insert(2, arg)

	if opts.verbose: add_flag('--verbose')
	if opts.offline: add_flag('--offline')
	if opts.refresh: add_flag('--refresh')
	if opts.command is not None:
		add_flag('--command=' + opts.command)

	logging.debug("calling: %r" % (cmd,))
	
	selections_string = subprocess.check_output(cmd)

	selections = minidom.parseString(selections_string)
	logging.debug("Got selections:\n%s" % (selections.toprettyxml(),))

	# URI-based feed:
	root_iface = selections.documentElement.getAttribute("interface")
	is_root = lambda s: s.getAttribute("interface") == root_iface
	impl_selection = filter_one(is_root, selections.getElementsByTagName("selection"), "interface==%s" % root_iface)

	root_feed = impl_selection.getAttribute("from-feed") or root_iface
	logging.debug("root feed: %s" % (root_feed,))
	
	local_feed_path = get_local_feed_file(root_feed)
	with open(local_feed_path) as feed_file:
		feed = minidom.parse(feed_file)
	# logging.debug("feed contents: %s" % (feed.toprettyxml()))

	selected_impl_id = impl_selection.getAttribute("id")
	if local_feed_path == root_feed and os.path.isabs(selected_impl_id):
		selected_impl_id = os.path.relpath(selected_impl_id, os.path.dirname(local_feed_path))

	active_impl = isolate_implementation(feed.documentElement, selected_impl_id)

	clean_feed(feed.documentElement, command=opts.command)

	for selection in selections.getElementsByTagName('selection'):
		url = selection.getAttribute("interface")

		package = selection.getAttribute("package")
		if package:
			logging.info("Skipping distribution package %s" % (package,))
			continue
		
		if url in opts.ignore:
			logging.info("Skipping ignored URL: %s" % (url,))

		local_feed = selection.getAttribute("from-feed")
		if local_feed and not local_feed:
			msg = "Local feed %s used for %s" % (local_feed, url)
			if url in opts.nonlocal:
				logging.info(msg)
			else:
				raise RuntimeError(msg)

		version = selection.getAttribute("version")
		req = feed.createElement("requires")
		req.setAttribute("interface", url)
		ver = feed.createElement("version")
		ver.setAttribute("not-before", version)

		next_version = Version.parse(version)
		if opts.exact:
			next_version = next_version.next()
		else:
			if opts.components > 0:
				# ensure version has at least `c` components
				components = itertools.chain(next_version.components, itertools.repeat(VersionComponent(0)))
				components = list(itertools.islice(components, opts.components))
				logging.debug("Freezing components: %s" % (list(map(str, components)),))
				logging.debug("inc component %s -> %s" % (components[-1], components[-1].increment()))
				components[-1] = components[-1].increment()
				next_version = Version(components)
			else:
				# negative values we just pass through increment
				next_version = next_version.increment(-opts.components)
		logging.info("Adding dependency on v%s - v%s of %s" % (version, next_version, url))

		ver.setAttribute("before", next_version.number)
		req.appendChild(ver)

		active_impl.appendChild(req)
	
	if output_file is None:
		filename = input_file.rstrip(r'\/')
		filename = re.split(r'[\/]', filename)[-1]
		stem, ext = os.path.splitext(filename)
		output_file = "%s-freeze%s" % (stem, ext or '.xml')

	output_contents = feed.toprettyxml()
	output_contents = re.sub('<!-- Base64 Signature.*\Z', '', output_contents, flags=re.MULTILINE | re.DOTALL)
	# cut out empty lines
	output_contents = re.sub('^\s*\n', '', output_contents, flags=re.MULTILINE)
	if output_file == '-':
		print(output_contents, end='')
	else:
		with open(output_file, 'w') as out:
			print(output_contents, file=out, end='')
		logging.info("Wrote %s" % (output_file))

if __name__ == '__main__':
	main()
