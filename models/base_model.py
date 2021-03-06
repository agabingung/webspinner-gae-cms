import datetime
import time
import logging
from google.appengine.ext import db
from appengine_utilities.rotmodel import ROTModel
from google.appengine.api import memcache
from utility.cache import Cache

wysiwyg_plugin = "tinymce"

SIMPLE_TYPES = (int, long, float, bool, dict, basestring)

def to_dict(model, ignore = []):
  output = {}
  output['id'] = model.key().__str__();
  for key, prop in model.properties().iteritems():
    if key in ignore:
     continue
    value = getattr(model, key)

    if value is None or isinstance(value, SIMPLE_TYPES):
      output[key] = value
    elif isinstance(value, datetime.date):
      # Convert date/datetime to ms-since-epoch ("new Date()").
      ms = time.mktime(value.utctimetuple()) * 1000
      ms += getattr(value, 'microseconds', 0) / 1000
      output[key] = int(ms)
    elif isinstance(value, list):
      if len(value) < 1 or isinstance(value[0], SIMPLE_TYPES):
        output[key] = value
      else:
        sublist = []
        for v in value:
          m = db.get(v)
          sublist.append(to_dict(m))
        output[key] = sublist
    elif isinstance(value, db.Model):
      output[key] = to_dict(value)
    else:
      raise ValueError('cannot encode ' + repr(prop))

  return output

class WsModel(ROTModel):
  class Relation():
    _relfields = []
    _modfields = []

    def __init__(self, relfields=[], modfields=[]):
      self._relfields = relfields
      self._modfields = modfields
  @classmethod
  def update(cls, dict_values, responsetype = 'Model'):
    if "key" in dict_values:
      model = db.get("".join(dict_values["key"]))
      for key, property in model.properties().iteritems():
        logging.info('Modifying property : ' + key)
        if key in dict_values:
          logging.info(key + ' in values')
          fitype = property.__class__.__str__(property)
          if ".StringListProperty" in fitype:
            dict_values[key] = [x.lstrip().rstrip() for x in "".join(dict_values[key]).split(",")]
          elif ".BooleanProperty" in fitype:
            dict_values[key] = "".join(dict_values[key]) != ""
          elif ".ReferenceProperty" in fitype:
            dict_values[key] = None if "".join(dict_values[key]) == "None" else db.get(dict_values[key])
          elif ".ListProperty" in fitype:
            dict_values[key] = [object.key() for object in db.get(dict_values[key])]
          else:
            dict_values[key] = "".join(dict_values[key])
          if dict_values[key]:
            setattr(model, key, dict_values[key])
      model.put()
      relations = model.__class__.relations()
      if len(relations._relfields) > 0:
        name = "edit_" + relations._relfields[0]["model"].lower() + "-" + relations._relfields[0]["value"].lower()
        if name in dict_values:
          if relations._relfields[0]["model"]:
            model_to = getattr( WsModel, relations._relfields[0]["model"])
            if model_to:
              model_to = db.get(dict_values[name])
              if model_to and len(model_to) > 0:
                if relations._relfields[0]["field"] in model_to[0].properties():
                  if ".ListProperty" in model_to[0].properties()[relations._relfields[0]["field"]].__str__():
                    list_model_keys = getattr(model_to[0], relations._relfields[0]["field"])
                    list_model_keys.append(model.key())
                    list_model_keys = list(set(list_model_keys))
                    setattr(model_to[0], relations._relfields[0]["field"], list_model_keys)
                  else:
                    setattr(model_to[0], relations._relfields[0]["field"], model)
                  model_to[0].put()
      WsModel.cache.clear()
      if responsetype == 'Model':
        return model
      elif responsetype == 'Dict':
        return to_dict(model)
      elif responsetype == 'Status':
        return True
    else:
      return None

  @classmethod
  def relations(cls):
    return cls.Relation()

  @classmethod
  def create(cls, dict_values, responsetype = 'Model'):
    model = cls()
    for key in dict_values:
      if key in cls.properties():
        fitype = cls.properties()[key].__str__()
        if ".StringListProperty" in fitype:
          dict_values[key] = [x.lstrip().rstrip() for x in "".join(dict_values[key]).split(",")]
        elif ".BooleanProperty" in fitype:
          dict_values[key] = dict_values[key] != ""
        elif ".ReferenceProperty" in fitype:
          try:
            dict_values[key] = db.get(dict_values[key])
          except:
            dict_values[key] = None
        elif ".ListProperty" in fitype:
          dict_values[key] = [object.key() for object in db.get("".join(dict_values[key]).split(","))]
        else:
          dict_values[key] = "".join(dict_values[key])
        setattr(model, key, dict_values[key])
    model.put()
    relations = model.__class__.relations()
    if len(relations._relfields) > 0:
      name = "add_" + relations._relfields[0]["model"].lower() + "-" + relations._relfields[0]["value"].lower()
      if name in dict_values:
        if getattr( WsModel, relations._relfields[0]["model"]):
          model_to = db.get(dict_values[name])
          logging.info('Model retrieved for key %s : %s' % (dict_values[name], model_to.__str__()))
          if model_to:
            if relations._relfields[0]["field"] in model_to.properties():
              if ".ListProperty" in model_to.properties()[relations._relfields[0]["field"]].__str__():
                list_model_keys = getattr(model_to, relations._relfields[0]["field"])
                list_model_keys.append(model.key())
                list_model_keys = list(set(list_model_keys))
                setattr(model_to, relations._relfields[0]["field"], list_model_keys)
              else:
                setattr(model_to, relations._relfields[0]["field"], model)
              model_to.put()
        else:
          logging.info('Model type %s not found in globals' % relations._relfields[0]['model'])
    
    if(cls.__name__ == "Page"):
      WsModel.cache.clear()
    if responsetype == 'Model':
      return model
    elif responsetype == 'Dict':
      return to_dict(model)
    elif responsetype == 'Status':
      return True

  @classmethod
  def to_edit_list(cls, display_field_name = "name", return_url = "/", include_security=False):
    html_out = '<ol class="%s-edit-list">' % cls.__name__.lower()
    models = WsModel.cache.get("%s_all" % cls.__name__.lower())
    if not models:
      models = cls.all().fetch(1000)
      WsModel.cache.add("%s_all" % cls.__name__.lower(), models)
    for model in models:
      link_html = "<li class='%s'><a href='/admin/delete/%s/%s.html?return_url=%s' class='delete'>delete</a><a href='/admin/edit/%s/%s.html?return_url=%s'>%s</a> "
      if include_security:
        link_html += " <a href='/admin/set_user_roles/%s.html?return_url=%s'>Modify Roles</a>" % (model.key(), return_url)
      link_html += '</li>'
      html_out += link_html % (cls.__name__.lower(),cls.__name__.lower(), model.key(), return_url,cls.__name__.lower(), model.key(), return_url,getattr(model, display_field_name))
    html_out += '</ol>'
    return html_out

  @classmethod
  def to_form(cls, return_url = "/", mode = "add", model_key = None, rel_key = None, admin = True):
    html_out = ""
    if model_key:
      model = cls.get(model_key)
      html_out += "<form action='/%s%s/%s/%s.html?return_url=%s' method='post'>" % ("admin/" if admin else "", mode, cls.__name__.lower(), model_key, return_url)
    else:
      model = cls()
      html_out += "<form action='/%s%s/%s.html?return_url=%s' method='post'>" % ("admin/" if admin else "", mode, cls.__name__.lower(), return_url)
    relations = model.__class__().relations()
    if rel_key and len(relations._relfields) > 0:
      model_name = relations._relfields[0]["model"].lower()
      name = mode + '_' + model_name + "-" + relations._relfields[0]["value"].lower()
      html_out += "<input type='hidden' value='%s' name='%s' id='%s' />" % (rel_key, name, name)
    for field in relations._modfields:
      key = field["name"]
      type = field["type"]
      if key in model.properties():
        finame = mode + '_' + cls.__name__.lower() + "-" + key
        html_out += "<label for'%s'>%s</label>" % (finame, cls.__name__ + " " + key.capitalize() + ":")
        textfields = ["text","email","password","url","tel"]
        value = getattr(model, key)
        value = value if value != None else ""
        if type in textfields:
          html_out += "<input type='%s' id='%s' name='%s' value='%s' />" % (type, finame, finame, value)
        elif type == "textlist":
          value = ", ".join(value)
          html_out += "<input type='%s' id='%s' name='%s' value='%s' />" % ("text", finame, finame, value)
        elif type == "textarea":
          html_out += "<textarea name='%s' id='%s'>%s</textarea>" % (finame,finame, value)
        elif type == "textareahtml":
          html_out += "<textarea name='%s' id='%s' class='%s'>%s</textarea>" % (finame,finame, wysiwyg_plugin, value)
        elif type == "select":
          if "list" in field:
            object_type = field["list"]
            objects = object_type.all().fetch(1000)
            def build_option(object):
              if model.is_saved():
                if object.key() == model.key():
                  return ""
              in_val = ""
              if field["list_val"] == "key":
                selected = " selected " if object == value else ""
                in_val = object.key()
              else:
                selected = " selected " if getattr(object, field["list_val"]) == value else ""
                in_val = getattr(object, field["list_val"])
              option_out = "<option value='%s' %s>%s</option>" % (in_val, selected, getattr(object, field["list_name"]))
              return option_out
            if field["list_name"] in object_type.properties():
              html_out += "<select name='%s' id='%s'>%s</select>" % (finame, finame, "<option value='None'>-- None --</option>" + "".join(map(build_option, objects)))
            else:
              html_out += "<select name='%s' id='%s'>%s</select>" % (finame, finame, ["<option value='%s'>%s</option>" % (object.key(), object.key().id()) for object in objects])
            
        elif type == "checkbox":
          checked = " checked " if value else ""
          html_out += "<input type='%s' name='%s' id='%s' %s />" % (type, finame, finame, checked)
        else:
          html_out += "<input type='%s' id='%s' name='%s' value='%s' />" % (relations._modfields[key], finame, finame, value)
      html_out += "<br />"
    html_out += "<input type='submit' name='%s.submit' id='%s.submit' value='Save' /></form>" % (cls.__name__.lower(), cls.__name__.lower())
    return html_out

  @classmethod
  def get_order_by_field(cls,keys = None, field = None, direction = "ASC"):
    models = []
    if keys is None:
      models = cls().all().fetch(10000)
    else:
      models = db.get(keys)
    if field in models[0].properties():
      direction = True if direction == "DESC" else False
      models = sorted(models, key = lambda model: getattr(model, field), reverse = direction)
    return models

  @classmethod
  def get_newest(cls, keys = None):
    return cls.get_order_by_field(keys, "date_created", "DESC")

  def sanity_check(self):
    result = {
      'checked' : [],
      'removed' : []
    }
    for key, property in self.properties().iteritems():
      fitype = property.__class__.__str__(property)
      if ".ListProperty" in fitype:
        result['checked'].append(key)
        for id in getattr(self, key):
          obj = db.get(id)
          if not obj:
            if not key in result:
              result[key] = []
            getattr(self, key).remove(id)
            result[key].append(id)
            result['removed'].append(id)
    if len(result['removed']) > 0:
      self.save()
    return result
  def to_dict(self, ignore=[]):
    return to_dict(self, ignore)

WsModel.db = db
WsModel.memcache = memcache
WsModel.cache = Cache()
