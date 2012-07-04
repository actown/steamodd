"""
Module for reading Steam Economy items

Copyright (c) 2010, Anthony Garcia <lagg@lavabit.com>

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted, provided that the above
copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
"""

import json, os, time, base, operator, re

class Error(Exception):
    def __init__(self, msg):
        Exception.__init__(self)
        self.msg = msg

    def __str__(self):
        return str(self.msg)

class SchemaError(Error):
    def __init__(self, msg, status = 0):
        Error.__init__(self, msg)
        self.msg = msg

class ItemError(Error):
    def __init__(self, msg, item = None):
        Error.__init__(self, msg)
        self.msg = msg
        self.item = item

class AssetError(Error):
    def __init__(self, msg, asset = None):
        Error.__init__(self, msg)
        self.msg = msg
        self.asset = asset

class BackpackError(Error):
    def __init__(self, msg):
        Error.__init__(self, msg)
        self.msg = msg

class schema(base.json_request):
    """ The base class for the item schema. """

    def create_item(self, oitem):
        """ Builds an item using this schema instance and returns it """

        return item(self, oitem)

    def get_language(self):
        """ Returns the ISO code of the language the instance
        is localized to """
        return self._language

    def get_attribute_definition(self, attrid):
        """ Returns the attribute definition dict of a given attribute
        id, can be the name or the integer ID """

        obj = self._get()
        attrs = obj["attributes"]
        attrdef = attrs.get(attrid)

        if not attrdef: return attrs.get(obj["attribute_names"].get(attrid.lower()))
        else: return attrdef

    def get_attributes(self):
        """ Returns all attributes in the schema """

        attrs = self._get("attributes")

        return [item_attribute(attr) for attr in sorted(attrs.values(),
                                                        key = operator.itemgetter("defindex"))]

    def get_qualities(self):
        """ Returns a list of all possible item qualities,
        each element will be a dict.
        prettystr is the localized pretty name (e.g. Valve)
        id is the numerical quality (e.g. 8)
        str is the non-pretty string (e.g. developer) """

        return self._get("qualities")

    def get_particle_systems(self):
        """ Returns a dictionary of particle system dicts keyed by ID """

        return self._get("particles")

    def get_kill_ranks(self):
        """ Returns a list of ranks for weapons with kill tracking """
        
        return self._get("item_ranks")

    def get_kill_types(self):
        """ Returns a dict with keys that are the value of
        the kill eater type attribute and values that are the name
        string """
        return self._get("kill_types")

    def get_origin_name(self, origin):
        """ Returns a localized origin name for a given ID """

        return self._get("origins")[int(origin)]["name"]

    def _deserialize(self, data):
        res = super(schema, self)._deserialize(data)
        obj = {}

        if not res or res["result"]["status"] != 1:
            raise SchemaError("Schema error", res["result"]["status"])

        attributes = {}
        attribute_names = {}
        for attrib in res["result"]["attributes"]:
            # WORKAROUND: Valve apparently does case insensitive lookups on these, so we must match it
            attributes[attrib["defindex"]] = attrib
            attribute_names[attrib["name"].lower()] = attrib["defindex"]
        obj["attributes"] = attributes
        obj["attribute_names"] = attribute_names

        items = res["result"]["items"]
        obj["items"] = dict(zip(map(operator.itemgetter("defindex"), items), items))

        qualities = {}
        for k, v in res["result"]["qualities"].iteritems():
            aquality = {"id": v, "str": k, "prettystr": k}

            try: aquality["prettystr"] = res["result"]["qualityNames"][aquality["str"]]
            except KeyError: pass

            qualities[v] = aquality
        obj["qualities"] = qualities

        particles = res["result"].get("attribute_controlled_attached_particles", [])
        obj["particles"] = dict(zip(map(operator.itemgetter("id"), particles), particles))

        levels = res["result"].get("item_levels", [])
        obj["item_ranks"] = dict(zip(map(operator.itemgetter("name"), levels),
                                     map(operator.itemgetter("levels"), levels)))

        killtypes = res["result"].get("kill_eater_score_types", [])
        obj["kill_types"] = dict(zip(map(operator.itemgetter("type"), killtypes), killtypes))

        origins = res["result"].get("originNames", [])
        obj["origins"] = dict(zip(map(operator.itemgetter("origin"), origins), origins))

        return obj

    def __iter__(self):
        return self.nextitem()

    def nextitem(self):
        obj = self._get()
        iterindex = 0
        iterdata = obj["items"].values()
        iterdata.sort(key = operator.itemgetter("defindex"))

        while(iterindex < len(iterdata)):
            data = self.create_item(iterdata[iterindex])
            iterindex += 1
            yield data

    def __getitem__(self, key):
        obj = self._get()
        realkey = None
        try: realkey = key["defindex"]
        except: realkey = key

        return self.create_item(obj["items"][realkey])

    def __len__(self):
        obj = self._get()
        return len(obj["items"].values())

    def __init__(self, appid, lang = None, **kwargs):
        """ schema will be used to initialize the schema if given,
        lang can be any ISO language code.
        lm will be used to generate an HTTP If-Modified-Since header. """

        self._language = base.get_language(lang)[0]
        self._app_id = str(appid)

        super(schema, self).__init__("http://api.steampowered.com/IEconItems_" + self._app_id +
                                     "/GetSchema/v0001/?key=" + base.get_api_key() + "&format=json&language=" + self._language,
                                     **kwargs)

class item(object):
    """ Stores a single TF2 backpack item """
    # The bitfield in the inventory token where
    # equipped classes are stored
    equipped_field = 0x1FF0000

    # Item image fields in the schema
    ITEM_IMAGE_SMALL = "image_url"
    ITEM_IMAGE_LARGE = "image_url_large"

    def get_attributes(self):
        """ Returns a list of attributes """

        item_attrs = []
        final_attrs = []
        sortmap = {"neutral" : 1, "positive": 2,
                   "negative": 3}

        if self._item != self._schema_item:
            try: item_attrs = self._item["attributes"]
            except KeyError: pass

        defaultattrs = {}
        for attr in self._schema_item.get("attributes", []):
            attrindex = attr.get("defindex", attr.get("name"))
            definition = self._schema.get_attribute_definition(attrindex)
            attrindex = definition["defindex"]
            defaultattrs[attrindex] = dict(definition.items() + attr.items())

        for attr in item_attrs:
            index = attr["defindex"]
            if index in defaultattrs:
                defaultattrs[index] = dict(defaultattrs[index].items() + attr.items())
            else:
                defaultattrs[index] = dict(self._schema.get_attribute_definition(index).items() + attr.items())

        sortedattrs = defaultattrs.values()
        sortedattrs.sort(key = operator.itemgetter("defindex"))
        sortedattrs.sort(key = lambda t: sortmap[t["effect_type"]])
        return [item_attribute(theattr) for theattr in sortedattrs]

    def get_quality(self):
        """ Returns a dict
        prettystr is the localized pretty name (e.g. Valve)
        id is the numerical quality (e.g. 8)
        str is the non-pretty string (e.g. developer) """

        qid = 0
        item = self._item
        qid = item.get("quality", self._schema_item.get("item_quality", 0))
        qualities = self._schema.get_qualities()

        try:
            return qualities[qid]
        except KeyError:
            return {"id": 0, "prettystr": "Broken", "str": "ohnoes"}

    def get_inventory_token(self):
        """ Returns the item's inventory token (a bitfield),
        deprecated. """
        return self._item.get("inventory", 0)

    def get_position(self):
        """ Returns a position in the backpack or -1 if there's no position
        available (i.e. an item isn't in the backpack) """

        inventory_token = self.get_inventory_token()

        if inventory_token == 0:
            return -1
        else:
            return inventory_token & 0xFFFF

    def get_equipped_classes(self):
        """ Returns a list of classes """
        equipped = self._item.get("equipped")

        if not equipped: return []

        # Yes I'm stubborn enough to use this for a WORKAROUND
        classes = set([slot["class"] for slot in
                       equipped if slot["class"] !=0 and slot["slot"] != 65535])

        return list(classes)

    def get_equipable_classes(self):
        """ Returns a list of classes that _can_ use the item. """
        classes = []
        sitem = self._schema_item

        try: classes = sitem["used_by_classes"]
        except KeyError: classes = self.get_equipped_classes()

        return classes

    def get_schema_id(self):
        """ Returns the item's ID in the schema. """
        return self._item["defindex"]

    def get_name(self):
        """ Returns the item's undecorated name """
        return self._schema_item["item_name"]

    def get_type(self):
        """ Returns the item's type. e.g. "Kukri" for the Tribalman's Shiv.
        If Valve failed to provide a translation the type will be the token without
        the hash prefix. """
        return self._schema_item["item_type_name"]

    def get_image(self, size):
        """ Returns the URL to the item's image, size should be one of
        ITEM_IMAGE_* """
        try:
            return self._schema_item[size]
        except KeyError:
            raise ItemError("Bad item image size given")

    def get_id(self):
        """ Returns the item's unique serial number if it has one """
        return self._item.get("id")

    def get_original_id(self):
        """ Returns the item's original ID if it has one. This is the last "version"
        of the item before it was customized or otherwise changed """
        return self._item.get("original_id")

    def get_level(self):
        """ Returns the item's level (e.g. 10 for The Axtinguisher) if it has one """
        return self._item.get("level")

    def get_slot(self):
        """ Returns the item's slot as a string, this includes "primary",
        "secondary", "melee", and "head". Will be None if the the item is unequippable """
        return self._schema_item.get("item_slot")

    def get_class(self):
        """ Returns the item's class
        (what you use in the console to equip it, not the craft class)"""
        return self._schema_item.get("item_class")

    def get_craft_class(self):
        """ Returns the item's class in the crafting system if it has one.
        This includes hat, craft_bar, or craft_token. """
        return self._schema_item.get("craft_class")

    def get_custom_name(self):
        """ Returns the item's custom name if it has one. """
        return self._item.get("custom_name")

    def get_custom_description(self):
        """ Returns the item's custom description if it has one. """
        return self._item.get("custom_desc")

    def get_quantity(self):
        """ Returns the number of uses the item has,
        for example, a dueling mini-game has 5 uses by default """
        return self._item.get("quantity", 1)

    def get_description(self):
        """ Returns the item's default description if it has one """
        return self._schema_item.get("item_description")

    def get_min_level(self):
        """ Returns the item's minimum level
        (non-random levels will have the same min and max level) """
        return self._schema_item.get("min_ilevel")

    def get_max_level(self):
        """ Returns the item's maximum level
        (non-random levels will have the same min and max level) """
        return self._schema_item.get("max_ilevel")

    def get_contents(self):
        """ Returns the item in the container, if there is one.
        This will be a standard item object. """
        rawitem = self._item.get("contained_item")
        if rawitem: return self._schema.create_item(rawitem)

    def is_untradable(self):
        """ Returns True if the item cannot be traded, False
        otherwise. """
        # Somewhat a WORKAROUND since this flag is there
        # sometimes, "cannot trade" is there somtimes
        # and then there's "always tradable". Opposed to
        # only occasionally tradable when it feels like it.
        untradable = self._item.get("flag_cannot_trade", False)
        if "cannot trade" in self:
            untradable = True
        return untradable

    def is_uncraftable(self):
        """ Returns True if the item cannot be crafted, False
        otherwise """
        return self._item.get("flag_cannot_craft", False)

    def is_name_prefixed(self):
        """ Returns False if the item doesn't use
        a prefix, True otherwise. (e.g. Bonk! Atomic Punch
        shouldn't have a prefix so this would be False) """
        return self._schema_item.get("proper_name", False)

    def get_full_item_name(self, prefixes = {}):
        """
        Generates a prefixed item name and is custom name-aware.

        Will use an alternate prefix dict if given,
        following the format of "non-localized quality": "alternate prefix"

        If you want prefixes stripped entirely call with prefixes = None
        If you want to selectively strip prefixes set the alternate prefix value to
        None in the dict

        """
        quality_str = self.get_quality()["str"]
        pretty_quality_str = self.get_quality()["prettystr"]
        custom_name = self.get_custom_name()
        item_name = self.get_name()
        language = self._schema.get_language()
        rank = self.get_rank()
        prefix = ""
        suffix = ""

        if item_name.find("The ") != -1 and self.is_name_prefixed():
            item_name = item_name[4:]

        if custom_name:
            item_name = custom_name
        else:
            try: suffix = "#" + str(int(self["unique craft index"].get_value()))
            except KeyError: pass

        if prefixes != None:
            prefix = prefixes.get(quality_str, pretty_quality_str)
            if rank: prefix = rank["name"]

        if prefixes == None or custom_name or (not self.is_name_prefixed() and quality_str == "unique"):
            prefix = ""

        if ((prefixes == None or language != "en_US") and (quality_str == "unique" or quality_str == "normal")):
            prefix = ""

        if (language != "en_US" and prefix):
            return item_name + " (" + prefix + ")"

        return ((prefix or "") + " " + item_name + " " + suffix).strip()

    def get_kill_eaters(self):
        """
        Returns a list of tuples containing the proper localized kill eater type strings and their values
        according to set/type/value "order"
        """

        # Order matters in how they show up in the tuple
        eaterspecs = {"type": "^kill eater user score type ?(?P<b>\d*)$|^kill eater score type ?(?P<a>\d*)$",
                      "count": "^kill eater user ?(?P<b>\d*)$|^kill eater ?(?P<a>\d*)$"}
        eaters = {}
        ranktypes = self._schema.get_kill_types()


        for attr in self:
            for name, spec in eaterspecs.iteritems():
                regexpmatch = re.match(spec, attr.get_name())
                if regexpmatch:
                    matchid = None
                    value = int(attr.get_value())
                    matchgroup = regexpmatch.groupdict()

                    # Ensure no conflicts between ranking this and non-attached attributes
                    for k, v in matchgroup.iteritems():
                        if v != None:
                            idsuffix = v or '0'
                            matchid = k + idsuffix

                    if matchid not in eaters:
                        eaters[matchid] = {}

                    eaters[matchid][name] = value
                    eaters[matchid]["aid"] = attr.get_id()

        eaterlist = []
        for key in eaters.keys():
            eater = eaters[key]
            count = eater.get("count")

            if count != None:
                rank = ranktypes.get(eater.get("type", 0), {"level_data": "KillEaterRanks", "type_name": "Count"})
                eaterlist.append((rank["level_data"], rank["type_name"], count, eater["aid"]))
        return eaterlist

    def get_rank(self):
        """
        Returns the item's rank (if it has one)
        as a dict that includes required score, name, and level.
        """

        if self._rank != {}:
            # Don't bother doing attribute lookups again
            return self._rank

        eaterlines = self.get_kill_eaters()

        if not eaterlines or eaterlines[0][2] == None:
            self._rank = None
            return None
        else: eaterlines = eaterlines[0]

        ranksets = self._schema.get_kill_ranks()
        try:
            rankset = ranksets[eaterlines[0]]
        except KeyError:
            rankset = [{"level": 0, "required_score": 0, "name": "Strange"}]
        realranknum = eaterlines[2]
        for rank in rankset:
            self._rank = rank
            if realranknum < rank["required_score"]:
                break

        return self._rank

    def get_styles(self):
        """ Returns all styles defined for the item """
        styles = self._schema_item.get("styles", [])

        return map(operator.itemgetter("name"), styles)

    def get_current_style_id(self):
        """ Returns the style ID of the item if it has one, this is used as an index """
        return self._item.get("style")

    def get_current_style_name(self):
        """ Returns the name of the style if it has one """
        styleid = self.get_current_style_id()
        if styleid:
            try:
                return self.get_styles()[styleid]
            except IndexError:
                return styleid

    def get_capabilities(self):
        """ Returns a list of capabilities, these are flags for what the item can do or be done with """
        caps = self._schema_item.get("capabilities")
        if caps: return caps.keys()
        else: return []

    def get_tool_metadata(self):
        """ Assume this will change. For now returns a dict of various information about tool items """
        return self._schema_item.get("tool")

    def get_origin_name(self):
        """ Returns the item's localized origin name """

        if "origin" in self._item:
            return self._schema.get_origin_name(self._item["origin"])

    def get_origin_id(self):
        """ Returns the item's origin ID """

        return self._item.get("origin")

    def __iter__(self):
        return self.nextattr()

    def nextattr(self):
        iterindex = 0
        attrs = self.get_attributes()

        while(iterindex < len(attrs)):
            data = attrs[iterindex]
            iterindex += 1
            yield data

    def __getitem__(self, key):
        for attr in self:
            if attr.get_id() == key or attr.get_name() == key:
                return attr

        raise KeyError(key)

    def __contains__(self, key):
        try:
            self.__getitem__(key)
            return True
        except KeyError:
            return False

    def __unicode__(self):
        return self.get_full_item_name()

    def __str__(self):
        return unicode(self).encode("utf-8")

    def __init__(self, schema, item):
        self._item = item
        self._schema = schema
        self._schema_item = None
        self._rank = {}

        # Assume it isn't a schema item if it doesn't have a name
        if schema and "item_name" not in self._item:
            try:
                sitem = schema._get("items")[self._item["defindex"]]
                self._schema_item = sitem
            except KeyError:
                raise ItemError("Item has no corresponding schema entry")
        else:
            self._schema_item = item

class item_attribute(object):
    """ Wrapper around item attributes """

    def get_value_formatted(self, value = None):
        """ Returns a formatted value as a string"""
        if value == None:
            val = self.get_value()
        else:
            val = value
        fattr = str(val)
        ftype = self.get_value_type()

        if ftype == "percentage":
            pval = int(round(val * 100))

            if self.get_type() == "negative":
                pval = 0 - (100 - pval)
            else:
                pval -= 100

            fattr = str(pval)
        elif ftype == "additive_percentage":
            pval = int(round(val * 100))

            fattr = str(pval)
        elif ftype == "inverted_percentage":
            pval = 100 - int(round(val * 100))

            if self.get_type() == "negative":
                if self.get_value_max() > 1:
                    pval = 0 - pval

            fattr = str(pval)
        elif ftype == "additive" or ftype == "particle_index" or ftype == "account_id":
            if int(val) == val: fattr = (str(int(val)))
        elif ftype == "date":
            d = time.gmtime(int(val))
            fattr = time.strftime("%Y-%m-%d %H:%M:%S", d)

        return fattr

    def get_description_formatted(self):
        """ Returns a formatted description string (%s* tokens replaced) """
        val = self.get_value()
        ftype = self.get_value_type()
        desc = self.get_description()

        if desc:
            return desc.replace("%s1", self.get_value_formatted())
        else:
            return None

    def get_name(self):
        """ Returns the attributes name """
        return self._attribute["name"]

    def get_class(self):
        return self._attribute["attribute_class"]

    def get_id(self):
        return self._attribute["defindex"]

    def get_value_min(self):
        """ Returns the minimum value for the attribute (not all attributes
        stay above this) """
        return self._attribute["min_value"]

    def get_value_max(self):
        """ Returns the maximum value for the attribute (not all attributes
        stay below this) """
        return self._attribute["max_value"]

    def get_type(self):
        """ Returns the attribute effect type (positive, negative, or neutral) """
        return self._attribute["effect_type"]

    def get_value(self):
        """ Returns the attribute's value, use get_value_type to determine
        the type. """
        return self._attribute.get("value")

    def get_description(self):
        """ Returns the attribute's description string, if
        it is intended to be printed with the value there will
        be a "%s1" token somewhere in the string. Use
        get_description_formatted to substitute this automatically. """
        return self._attribute.get("description_string")

    def get_value_type(self):
        """ Returns the attribute's type. Currently this can be one of
        additive: An integer (convert value to integer) or boolean
        percentage: A standard percentage
        additive_percentage: Could represent a percentage that adds to default stats
        inverted_percentage: The sum of the difference between the value and 100%
        date: A unix timestamp """
        try: return self._attribute["description_format"][9:]
        except KeyError: return None

    def is_hidden(self):
        """ Returns True if the attribute is "hidden"
        (not intended to be shown to the end user). Note
        that hidden attributes also usually have no description string """
        if self._attribute.get("hidden", True) or self.get_description() == None:
            return True
        else:
            return False

    def get_account_info(self):
        """ Certain attributes have a user's account information
        associated with it such as a gifted or crafted item.

        Returns: A dict with two keys: `persona' and `id64'.
        None if the attribute has no account information attached to it. """
        account_info = self._attribute.get("account_info")
        if account_info:
            return {"persona": account_info.get("personaname", ""),
                    "id64": account_info["steamid"]}
        else:
            return None

    def __unicode__(self):
        """ Pretty printing """
        if not self.is_hidden():
            return self.get_description_formatted()
        else:
            return self.get_name() + ": " + self.get_value_formatted()

    def __str__(self):
        return unicode(self).encode("utf-8")

    def __init__(self, attribute):
        self._attribute = attribute

        if "float_value" in self._attribute and self.get_value_type() != "date":
            fattr = self._attribute["float_value"]
            isint = self._attribute.get("stored_as_integer")

            if (not isint) or (isint and (round(fattr) == fattr) and fattr != 0.0):
                self._attribute["value"] = fattr

class backpack(base.json_request):
    """ Functions for reading player inventory """

    def get_total_cells(self):
        """ Returns the total number of cells in the backpack.
        This can be used to determine if the user has bought a backpack
        expander. """

        cells = self._get("cells")
        return cells

    def set_schema(self, schema):
        """ Sets a new schema to be used on inventory items """
        self._schema = schema

    def __iter__(self):
        return self.nextitem()

    def __len__(self):
        items = self._get("items")
        return len(items)

    def nextitem(self):
        iterindex = 0
        iterdata = self._get("items")

        while(iterindex < len(iterdata)):
            data = iterdata[iterindex]
            iterindex += 1
            yield data

    def _deserialize(self, data):
        res = super(backpack, self)._deserialize(data)
        obj = {}

        status = res["result"]["status"]

        if status == 8:
            raise BackpackError("Bad SteamID64 given")
        elif status == 15:
            raise BackpackError("Profile set to private")
        elif status != 1:
            raise BackpackError("Unknown error")

        items = res["result"]["items"]
        obj = {
            "items": [self._schema.create_item(item) for item in items if item],
            "cells": res["result"].get("num_backpack_slots", len(items))
            }

        return obj

    def _get(self, value = None):
        if not self._schema:
            self._schema = schema()

        return super(backpack, self)._get(value)

    def __init__(self, appid, profile, oschema = None):
        """ Loads the backpack of user sid if given,
        generates a fresh schema object if one is not given. """

        self._schema = oschema
        self._app_id = str(appid)

        try:
            sid = profile.get_id64()
        except:
            sid = str(profile)

        url = ("http://api.steampowered.com/IEconItems_{0}/GetPlayerItems/v0001/?key={1}&format=json&SteamID={2}").format(
            self._app_id,
            base.get_api_key(),
            sid)

        super(backpack, self).__init__(url)

class asset_item:
    def __init__(self, asset, catalog):
        self._catalog = catalog
        self._asset = asset

    def __unicode__(self):
        return self.get_name() + " " + str(self.get_price())

    def __str__(self):
        return unicode(self).encode("utf-8")

    def get_tags(self):
        """ Returns a dict containing tags and their localized labels as values """

        return dict([(t, self._catalog.get_tag_map().get(t, t)) for t in
                     self._asset.get("tags")])


    def get_price(self, nonsale = False):
        """ Returns a dict containing prices for all available
        currencies or a single price otherwise. If nonsale is
        True normal prices will always be returned, even if there
        is currently a discount """

        asset = self._asset
        price = None
        currency = self._catalog.get_currency()
        pricedict = asset["prices"]

        if nonsale: pricedict = asset.get("original_prices", asset["prices"])

        if currency:
            try:
                price = float(pricedict[currency.upper()])/100
                return price
            except KeyError:
                return None
        else:
            return dict([(p[0], float(p[1]) / 100) for p in pricedict.iteritems()])

    def get_name(self):
        return self._asset.get("name")

class assets(base.json_request):
    """ Class for building asset catalogs """

    def get_currency(self):
        """ Returns the currency, this will be None if no
        preference is set """

        return self._currency

    def get_tag_map(self):
        """ Returns a dict containing internal tag names and
        their labels """

        return self._get("tags")

    def __getitem__(self, key):
        assets = self._get("assets")

        try:
            return assets[str(key.get_schema_id())]
        except:
            return assets[str(key)]

    def __iter__(self):
        return self._nextitem()

    def _nextitem(self):
        assets = self._get("assets")
        data = sorted(assets.values(), key = asset_item.get_name)
        iterindex = 0

        while iterindex < len(data):
            ydata = data[iterindex]
            iterindex += 1
            yield ydata

    def _deserialize(self, data):
        obj = {"assets": {}}
        res = super(assets, self)._deserialize(data)

        if "result" not in res: raise AssetError("Bad asset list")
        else: res = res["result"]

        if not res.get("success", False): raise AssetError("Asset server error")

        try:
            obj["tags"] = res["tags"]
            obj["assets"] = dict([(asset["name"], asset_item(asset, self)) for asset in
                                  res["assets"]])
        except KeyError as E:
            raise AssetError("Missing key in asset catalog: " + str(E))

        return obj

    def __init__(self, appid, lang = None, currency = None, **kwargs):
        """ lang: Language of asset tags, defaults to english
        currency: The iso 4217 currency code, returns all currencies by default """

        self._language = base.get_language(lang)[0]
        self._currency = currency
        self._app_id = appid

        url = ("http://api.steampowered.com/ISteamEconomy/GetAssetPrices/v0001?" +
               "key={0}&format=json&language={1}&appid={2}".format(base.get_api_key(),
                                                                   self._language,
                                                                   self._app_id))
        if self._currency: url += "&currency=" + self._currency

        super(assets, self).__init__(url, **kwargs)
