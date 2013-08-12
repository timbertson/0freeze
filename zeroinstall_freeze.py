#!/usr/bin/env python
from __future__ import print_function
import optparse
import subprocess
import os
import sys
import logging
import urllib
import version
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

def clean_feed_element(elem):
	for e in elem.childNodes[:]:
		if e.nodeType != dom.Node.ELEMENT_NODE: continue
		#TODO: check exhaustiveness
		if e.tagName in ['group', 'requires', 'command', 'interface']: continue
		logging.debug("Cleanup: remove %s" % (e.tagName))
		elem.removeChild(e)

def isolate_implementation(feed, impl_id):
	# get active implementation, and delete all others:
	all_impls = feed.documentElement.getElementsByTagName("implementation")
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
	p.add_option('-c', '--command')
	opts, args = p.parse_args()
	logger.setLevel(level=logging.DEBUG if opts.verbose else logging.INFO)
	input_file = args.pop(0)
	if len(args) > 0:
		assert len(args) == 1, 'too many arguments'
		output_file, = args
	
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
	logging.debug("Got selections:\n%s" % (selections_string,))

	selections = minidom.parseString(selections_string)
	logging.debug(selections.toprettyxml())

	# URI-based feed:
	root_iface = selections.documentElement.getAttribute("interface")
	is_root = lambda s: s.getAttribute("interface") == root_iface
	impl_selection = filter_one(is_root, selections.getElementsByTagName("selection"), "interface==%s" % root_iface)

	root_feed = impl_selection.getAttribute("from-feed") or root_iface
	logging.debug("root feed: %s" % (root_feed,))
	
	local_feed_path = get_local_feed_file(root_feed)
	with open(local_feed_path) as feed_file:
		feed = minidom.parse(feed_file)
	logging.debug("feed contents: %s" % (feed.toprettyxml()))

	selected_impl_id = impl_selection.getAttribute("id")
	if local_feed_path == root_feed and os.path.isabs(selected_impl_id):
		selected_impl_id = os.path.relpath(selected_impl_id, os.path.dirname(local_feed_path))

	active_impl = isolate_implementation(feed, selected_impl_id)

	clean_feed_element(feed.documentElement)

	for selection in selections.getElementsByTagName('selection'):
		url = selection.getAttribute("from-feed") or selection.getAttribute("interface")
		if url.startswith("distribution:"):
			logging.info("Skipping distribution package %s" % (selection.getAttribute("package"),))
			continue

		version = selection.getAttribute("version")
		logging.debug("Adding dependency on version %s of %s" % (version, url))
		req = feed.createElement("requires")
		req.setAttribute("interface", url)
		ver = feed.createElement("version")
		ver.setAttribute("not-before", version)

		#TODO: proper increment
		ver.setAttribute("before", version + '-post')
		req.appendChild(ver)

		active_impl.appendChild(req)
	
	print(feed.toprettyxml())

if __name__ == '__main__':
	main()
