'''
Copyright (c) 2010, Webspinner CMS
All rights reserved.

Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:
Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
Neither the name of the appengine-utilities project nor the names of its contributors may be used to endorse or promote products derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
'''
import os
import __main__
import time
from google.appengine.api import urlfetch
from google.appengine.ext.webapp import template
from appengine_utilities import sessions
from appengine_utilities import flash
from appengine_utilities import event
from appengine_utilities import cache
from appengine_utilities.rotmodel import ROTModel
import wsgiref.handlers
from google.appengine.ext import webapp
from google.appengine.api import memcache, users
from google.appengine.ext import db
from django.utils import simplejson
import hashlib
import re
from models import *

class Webspinner():
  def __init__(self):
    self.site = Site.all().get()

  class navigation:
    @classmethod
    def get_nav_list(cls, site):
      html_out = "<ul class='site_menu'>"
      pages = Page.all().filter('site', site).fetch(500)
      def top_level(page):
        if not page.ancestor:
          return True
        else:
          return False        
      top_level_pages = filter(top_level, pages)
      for page in top_level_pages:
        add_page_to_menu(page)
      def add_page_to_menu(page):
        html_out += "<li class='menu_item top_level'><a href='%s' class='menu_item_link'>%s</a>" % (page.page_chain, page.menu_name)
        children = filter(lambda x: x.ancestor == page, pages)
        if children:
          html_out += "<ul>"
          for p in children:
            add_page_to_menu(p)
          html_out += "</ul>"
        html_out += "</li>"
      return html_out

  class users:
    @classmethod
    def get_current_user(cls, handler):
      if 'user' in handler.session:
        user = User.get(handler.session['user'])
        return user
      else:
        return None
        
    @classmethod
    def is_current_user_admin(cls, handler):
      if u'user' in handler.session:
        user = User.get(handler.session['user'])
        role = Role.all().filter("name", "Administrator").get()
        if role.key() ==  user.role.key():
          return True
        else:
          return False
      else:
        return False
          
    @classmethod
    def create_login_url(ws, return_page):
      return "/login?return_url=%s" % return_page
    @classmethod
    def create_logout_url(ws, return_page):
      return "/logout?return_url=%s" %return_page

class Handler(webapp.RequestHandler):
  def __init__(self):
    self.ws = Webspinner()
    self.session = sessions.Session()
    
  def json_out(self, data):
    self.response.headers.add_header("Content-Type","application/json")
    self.response.out.write(simplejson.dumps(data))
  def render_out(self, template_file, values = {}):
    self.response.out.write(template.render(template_file,values))
  def render_string_out(self, template_object, template_values):
    context = template.Context(template_values)
    self.response.out.write(template_object.render(context))

class GetPage(Handler):
  def get(self):
    if self.ws.site is None:
      self.redirect('/install')
      return False
    path = self.request.path
    query_string = self.request.query_string
    #print path
    page_chain = path
    query_chain = query_string.split("&")
    def kv_q(x):
      x = x.split('=')
      if len(x) < 2:
        return x[0]
      return {x[0]: x[1]}
    query_chain_kv = map(kv_q, query_chain)
    page = Page.get_by_page_chain(page_chain)
    if page:
      page_theme = page.theme
      #print page.build_template()
      page_html = "<title>%s</title><style>%s</style><script src='http://ajax.googleapis.com/ajax/libs/jquery/1.4.2/jquery.min.js' type='text/javascript'></script><script type='text/javascript'>%s</script>%s" % (page.title, page_theme.css, page_theme.js, page.build_template())
      page_template = template.Template(page_html)
      template_values = {"page": page, "sections": page.sections()}
      self.render_string_out(page_template, template_values)
    else:
      self.error(404) #self.json_out({'page_chain':page_chain,'query_chain':query_chain_kv})

class Install(Handler):

  def get(self):
    site = Site.all().get()
    if(site):
      self.redirect("/")
    self.render_out("templates/install.html")
  def post(self):
    site = Site.all().get()
    if(site):
      self.redirect("/")
    save_items = {'site.title':'','site.admin':'','site.password':''}
    form_items = ['site.title','site.admin','site.password']
    for item in form_items:
      if item in self.request.arguments():
        if self.request.get(item) != "":
          save_items[item] = self.request.get(item)
        else:
          self.json_out({"success":False,"message":"%s is not entered" % item})
          return False
      else:
        self.json_out({"success":False,"message":"%s is not in the form" % item})
        return False
    user = users.get_current_user()
    site = Site.create(save_items['site.admin'],save_items['site.password'],save_items['site.title'],user)
    self.redirect('/')

class Login(Handler):
  def get(self):
    template_values = {'return_url': self.request.get("return_url")}
    self.render_out("templates/login.html", template_values)
  def post(self):
    if 'user.email' not in self.request.arguments() or 'user.password' not in self.request.arguments():
      self.json_out({'success': False,'message': 'Login invalid, not a legitamate form'})
    if self.request.get('user.email') == "" or  self.request.get('user.password') == "":
      self.json_out({'success': False,'message': 'Please enter your email address and password to login'})
    login = User.login(self.request.get('user.email'),self.request.get('user.password'),self.ws.site)
    if login:
      self.session["user"] = login
      #print self.session["user"]
      self.redirect(self.request.get("return_url"))
    else:
      self.session.delete_item("user")
      self.redirect(self.request.get("return_url"))

class Logout(Handler):
  def get(self):
    self.session.delete_item("user")
    self.redirect(self.request.get("return_url"))

class Administrate(Handler):
  def get(self):
    user = self.ws.users.get_current_user(self)
    if user == None:
      self.redirect(self.ws.users.create_login_url('/admin'))
    else:
      is_admin = self.ws.users.is_current_user_admin(self)
      if(is_admin):
        theme_packages = ThemePackage.all().fetch(100)
        themes = Theme.all().fetch(100)
        pages = Page.all().fetch(100)
        roles = Role.all().fetch(100)
        actions = ACTIONS
        _users = User.all().fetch(100)
        template_values = {'logout_url':self.ws.users.create_logout_url('/'),'theme_packages': theme_packages,'themes': themes, 'pages': pages, 'roles':roles, 'users':_users, 'actions': actions, 'site': self.ws.site}
        self.response.out.write(template.render('templates/manage.html',template_values))
      else:
        self.redirect("/")

class ImageHandler(Handler):
  def get(self):
    name = self.request.path.split('/')[2]
    image = Image.get_by_name(name)
    if image and image.file:
      self.response.headers['Content-Type'] = 'image/JPEG'
      self.response.out.write(image.file)
    else:
      self.json_out({"name": name})

class AddItem(Handler):
  def get(self, type):
    if type.capitalize() in globals():
      cls = globals()[type.capialize()]
      if cls:
        fields = cls().properties()
        self.render_out("form.html", fields)
  def post(self, type):
    if type.capitalize() in globals():
      cls = globals()[type.capitalize()]
      if cls:
        #self.response.out.write(dir(cls))
        values = {}
        for k in self.request.arguments():
          value = self.request.get(k)
          if k.split('.')[-1] in cls().properties() and "List" in cls().properties()[k.split('.')[-1]].__class__().__str__():
            values[k.split('.')[-1]] = [x.lstrip().rstrip() for x in value.split(",")]
          else:
            values[k.split('.')[-1]] = value
        values[k] = self.request.get(k)
        result = cls.create(values)
        self.response.out.write(values)
      else:
        self.response.out.write(self.request)
      #self.response.out.write(dir(record._properties[record._properties.keys()[0]].__subclasshook__))

ROUTES = [('/admin', Administrate),
                    ('/admin/add/(.+)', AddItem),
                    ('/login', Login),
                    ('/logout', Logout),
                    ('/install', Install),
                    ('/images/.*/[sbtl]', ImageHandler),
                    ('/.*', GetPage),]


def main():
  application = webapp.WSGIApplication(
                                       ROUTES,
                                       debug=True)
  wsgiref.handlers.CGIHandler().run(application)

if __name__ == "__main__":
  main()
