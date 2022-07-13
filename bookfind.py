#!/usr/bin/env python3

#
# bookfind.py
#
# Author       : Finn Rayment <finn@rayment.fr>
# Date created : 12/03/2022
#

import argparse
import copy
import csv
from html.parser import HTMLParser
from sys import exit
import urllib.parse
import urllib.request

API_URL = 'https://bookfinder.com/search/'
DEFAULT_CURRENCY = 'EUR'
DEFAULT_DESTINATION = 'fr'
JUSTIFY = 11
LINE_LEN = 80 # chars per line

VERSION = '1.2.0' # make sure to update on version change

argp = argparse.ArgumentParser(description='Find books at the best price')
argp.add_argument('-v', '--version',
                  action='version',
                  version='%(prog)s {}'.format(VERSION))
argp.add_argument('-c', '--currency',
                  metavar='sym',
                  help='3 letter currency symbol (default: EUR)',
                  type=str)
argp.add_argument('-d', '--destination',
                  metavar='sym',
                  help='2 letter country-code (default: FR)',
                  type=str)
argp.add_argument('-l', '--limit',
                  metavar='num',
                  help='limit the number of results',
                  default=0,
                  type=int)
argp.add_argument('-o', '--output',
                  metavar='file',
                  help='output results to a CSV file',
                  type=str)
argp.add_argument('-n', '--new',
                  help='search for new books (default)',
                  action='store_true')
argp.add_argument('-u', '--used',
                  help='search for used books',
                  action='store_true')
argp.add_argument('isbn',
                  help='SBN, ISBN-10 or ISBN-13 number to search',
                  type=str)
args = argp.parse_args()

def sanitise_isbn(isbn):
	return ''.join(i for i in str(isbn) if i.isdigit())

def check_isbn(isbn):
	if len(isbn) == 9:
		# convert SBN to ISBN-10
		isbn = '0' + isbn
	if len(isbn) == 10:
		# ISBN-10
		s = 0
		t = 0
		for i in range(10):
			t += int(isbn[i])
			s += t
		return s % 11 == 0
	elif len(isbn) == 13:
		# ISBN-13
		o = [int(i) for i in isbn[::2]]
		e = [int(i)*3 for i in isbn[1::2]]
		return (sum(o)+sum(e)) % 10 == 0
	else:
		return False

def form_url(isbn, currency, destination):
	# encode the url properly
	isbn = urllib.parse.quote(isbn)
	currency = urllib.parse.quote(currency)
	return API_URL + '?keywords=' + isbn + '&currency=' + currency + \
	       '&destination=' + destination + '&lang=en&st=sh&ac=qr&submit='

def fetch_book(isbn, currency, destination):
	url = form_url(isbn, currency, destination)
	data = urllib.request.urlopen(url)
	return data

SECTION_IGNORE1  = 0
SECTION_NEW      = 1
SECTION_USED     = 2
SECTION_IGNORE2  = 3

DESC_NONE        = 0
DESC_PUBLISHER   = 1
DESC_EDITION     = 2
DESC_LANGUAGE    = 3

DATA_NONE        = 0
DATA_TITLE       = 1
DATA_DESCRIPTION = 2
DATA_PRICE       = 3

class BookHTMLParser(HTMLParser):
	def __init__(self):
		super().__init__()
		self.section = 0
		self.books_new = []
		self.books_used = []
		self.entry_default = {
			'price':None, 'date':None, 'url':None, 'desc':[]
		}
		self.entry = copy.deepcopy(self.entry_default)
		self.adding = False
		self.data_fetch = DATA_NONE
		self.desc_fetch = DESC_NONE
		self.desc_fetch_tmp = DESC_NONE
		self.title = None
		self.publisher = None
		self.edition = None
		self.language = None

	def extract_title(self):
		return self.title

	def extract_publisher(self):
		return self.publisher

	def extract_edition(self):
		return self.edition

	def extract_language(self):
		return self.language

	def extract_new(self):
		return self.books_new

	def extract_used(self):
		return self.books_used

	def handle_starttag(self, tag, attrs):
		if tag == 'br' or tag == 'link':
			return
		if tag == 'a':
			if self.data_fetch == DATA_PRICE:
				for attrib in attrs:
					if attrib[0] == 'href':
						bigurl = str(attrib[1])
						# the URL is encoded as a redirect link with the target
						# URL hidden within as an encoded parameter - we need to
						# extract this URL
						parsed = urllib.parse.urlparse(bigurl)
						urlparts = urllib.parse.parse_qs(parsed.query)
						self.entry['url'] = urlparts['bu'][0]
						break
			if self.data_fetch == DATA_DESCRIPTION:
				# cancel description scraping because <a> links in the desc are
				# normally amazon prime links or other garbage that we don't
				# need
				self.data_fetch = DATA_NONE
			return
		self.data_fetch = DATA_NONE
		for attrib in attrs:
			if attrib[0] == 'id' and attrib[1] == 'describe-isbn-title':
				self.data_fetch = DATA_TITLE
			if attrib[0] == 'class' and attrib[1] == 'describe-isbn':
				self.desc_fetch_tmp += 1
				self.desc_fetch += self.desc_fetch_tmp
			if attrib[0] == 'class' and attrib[1] == 'results-table-Logo':
				self.section += 1
			if attrib[0] == 'data-price':
				# only add if we've already started adding.
				# 'data-price' is only found at the start of a new entry
				if self.adding is True:
					if self.section == SECTION_NEW:
						self.books_new += [copy.deepcopy(self.entry)]
					elif self.section == SECTION_USED:
						self.books_used += [copy.deepcopy(self.entry)]
					self.entry = copy.deepcopy(self.entry_default)
				self.adding = True
			if attrib[0] == 'class' and attrib[1] == 'results-price':
				self.data_fetch = DATA_PRICE
			if attrib[0] == 'data-pub_date':
				self.entry['date'] = str(attrib[1])
			if attrib[0] == 'class' and attrib[1] == 'item-note':
				self.data_fetch = DATA_DESCRIPTION

	def money_strip(self, price_str):
		stripped = ''
		dot = False
		for c in price_str:
			if c.isdigit() or (not dot and c == '.'):
				stripped += c
				if c == '.':
					dot = True
		return stripped

	def handle_data(self, data):
		data = data.strip()
		#if self.data_fetch != DATA_NONE:
		#	print('<<<', data, '>>>')
		if data == '':
			return
		if self.data_fetch == DATA_TITLE:
			self.title = str(data)
		elif self.data_fetch == DATA_DESCRIPTION:
			self.entry['desc'] += [str(data)]
		elif self.data_fetch == DATA_PRICE:
			self.entry['price'] = str(data)
			self.entry['price_raw'] = float(self.money_strip(str(data)))
		elif self.desc_fetch == DESC_PUBLISHER:
			self.publisher = str(data)
		elif self.desc_fetch == DESC_EDITION:
			self.edition = str(data)
		elif self.desc_fetch == DESC_LANGUAGE:
			self.language = str(data)
		self.desc_fetch = DESC_NONE

def print_align(header, data, color=None, gap=0, just=0):
	align = ''.ljust(JUSTIFY+just)
	gapalign = ''.ljust(gap)
	if not isinstance(data, list):
		data = [data]
	for idx,i in enumerate(data):
		hdr = header.ljust(JUSTIFY+just)
		if color is not None:
			hdr = str(color) + hdr + '\033[00m'
		if idx == 0:
			print(gapalign + hdr, ':', str(i).strip())
		else:
			print(gapalign + align + '  ', i.strip())

def output_results(parser, isbn, filename):
	title      = parser.extract_title()
	publisher  = parser.extract_publisher()
	edition    = parser.extract_edition()
	language   = parser.extract_language()
	books_new  = sorted(parser.extract_new(), key=lambda d:d['price_raw'])
	books_used = sorted(parser.extract_used(),key=lambda d:d['price_raw'])
	if args.limit > 0:
		books_new = books_new[:args.limit]
		books_used = books_used[:args.limit]
	if filename is None:
		# books are printed from most expensive to cheapest
		books_new.reverse()
		books_used.reverse()
	if title is None:
		print('error: no book could be found')
		exit(1)
	if filename is not None:
		# we're dumping to csv - remove unnecessary columns and add others
		for book in books_new:
			book.pop('desc')
			book.pop('price')
			book.pop('date')
			book['isbn'] = isbn
			book['condition'] = 'new'
		for book in books_used:
			book.pop('desc')
			book.pop('price')
			book.pop('date')
			book['isbn'] = isbn
			book['condition'] = 'used'
		with open(filename, 'w') as f:
			w = csv.writer(f)
			if len(books_new) > 0:
				w.writerow(books_new[0])
			else:
				w.writerow(books_used[0])
			if args.new is True or args.used is False:
				for book in books_new:
					w.writerow(book.values())
			if args.used:
				for book in books_used:
					w.writerow(book.values())
	else:
		if args.used:
			print()
			for book in books_used:
				print('-' * (LINE_LEN // 2))
				print('\033[91mPrice\033[00m :', book['price'])
				print_align('Date', book['date'], gap=4)
				print_align('Description', book['desc'], gap=4)
				print_align('URL', book['url'], gap=4)
				print()
			print('\033[92mUsed books\033[00m')
		if args.new is True or args.used is False:
			print()
			for book in books_new:
				print('-' * (LINE_LEN // 2))
				print('\033[91mPrice\033[00m :', book['price'])
				print_align('Date', book['date'], gap=4)
				print_align('Description', book['desc'], gap=4)
				print_align('URL', book['url'], gap=4)
				print()
			print('\033[92mNew books\033[00m')
		print()
		print_align('Tile', title, color='\033[93m')
		print_align('Publisher', publisher, color='\033[93m')
		print_align('Edition', edition, color='\033[93m')
		print_align('Language', language, color='\033[93m')

try:
	isbn = sanitise_isbn(args.isbn)
	if (len(isbn) != 9 and len(isbn) != 10 and len(isbn) != 13) or \
	   not check_isbn(isbn):
		print('error: not a valid SBN, ISBN-10 or ISBN-13 number')
		exit(1)
	if len(isbn) == 9:
		# convert SBN to ISBN-10
		isbn = '0' + isbn
	currency = args.currency
	destination = args.destination
	if currency is None:
		currency = DEFAULT_CURRENCY
	else:
		currency = currency.upper()
	if destination is None:
		destination = DEFAULT_DESTINATION
	else:
		destination = destination.lower()
	if args.output is not None:
		print('fetching and saving to CSV - this may take some time...')
	data = fetch_book(isbn, currency, destination)
	htmldata = data.read()
	try:
		htmldata = htmldata.decode('windows-1252')
	except Exception:
		htmldata = htmldata.decode('UTF-8')
	parser = BookHTMLParser()
	parser.feed(htmldata)
	output_results(parser, isbn, args.output)
except urllib.error.URLError as e:
	err = str(e)
	print('error: unable to fetch entry')
	if len(err) > 0:
		print('\tURLError: ' + err)
	exit(1)
except KeyError as e:
	err = str(e)
	print('error: unable to find entry')
	if len(err) > 0:
		print('\tKeyError: ' + err)
	exit(1)
except Exception as e:
	err = str(e)
	print('error: unexpected error')
	if len(err) > 0:
		print('\tException: ' + err)
	exit(1)

