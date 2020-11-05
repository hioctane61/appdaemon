import hassapi as hass
import datetime

class SmartHeat(hass.Hass):
    
    def initialize(self):
        
        evening = self.parse_time(self.args["evening_on"])
        self.run_daily(self.evening, evening, constrain_days="mon,tue,wed,thu,fri")
        morning_weekend = self.parse_time(self.args["morning_on_weekend"])
        self.run_daily(self.morning, morning_weekend, constrain_days="sat,sun")
        check_times = self.args["check_times"]
        self.upstairs_entity = self.args["upstairs_temp_sensors"]
        self.downstairs_entity = self.args["downstairs_temp_sensors"]
        self.outside_entity = self.args["outside_temp_sensors"]
        self.thermostat = self.args["thermostat"]
        
        self.hot_water_entity = self.args["hot_water_entity"]
        hot_water_time_on = self.parse_time(self.args["hot_water_on"])
        hot_water_time_off = self.parse_time(self.args["hot_water_off"])
        self.hot_water_time_duration = self.args["hot_water_heat_duration_mins"]
        self.run_daily(self.hot_water, hot_water_time_on)
        self.run_daily(self.hot_water, hot_water_time_off)
        self.listen_state(self.hw_boost, self.hot_water_entity)
        
        for check_time in check_times:
            check_time_obj = self.parse_time(check_time)
            if check_time == r'18:30:00':
                self.run_daily(self.heat_check, check_time_obj, constrain_days="mon,tue,wed,thu,fri")
            else:
                self.run_daily(self.heat_check, check_time_obj)
    
        morning_week = self.parse_time(self.args["morning_on_week"])
        self.run_daily(self.morning, morning_week, constrain_days="mon,tue,wed,thu,fri")
        
        bedtime = self.parse_time(self.args["night_time_off"])
        self.run_daily(self.bedtime, bedtime)

        self.listen_state(self.switch, "binary_sensor.people_home")
        
        self.boost_duration_sec = float(self.args["boost_duration_mins"]) * 60
        boost_time = self.parse_time(self.args["boost_time"])
        self.run_daily(self.boost, boost_time)
        ##################
        ##################

    def hw_boost(self, entity, attribute, old, new, kwargs):
        if new != old:
            if new == r'on':
                duration = int(self.hot_water_time_duration * 61)
                self.run_in(self.turn_off_hw, duration)

    def hot_water(self, kwargs):
        manual = self.get_state("input_boolean.manual_thermostat")
        if manual == r'off':
            hw_state = self.get_state(self.hot_water_entity)
            if hw_state == r'off':
                self.turn_off_heat()
                self.run_in(self.turn_on_hw, 60)
            elif hw_state == r'on':
                self.run_in(self.turn_off_hw, 0)
            else:
                self.log(f"hot water in unknown state: {hw_state}")


    def turn_on_hw(self, kwargs):
        self.log("Turning on hot water")
        self.turn_on(self.hot_water_entity)

    def turn_off_hw(self, kwargs):
        hw_state = self.get_state(self.hot_water_entity)
        if hw_state == r'on':
            self.log("Turning off hot water")
            self.turn_off(self.hot_water_entity)


    def average(self, lst): 
        return round(sum(lst) / len(lst),1) 

    def logbook(self, myname=None, mymessage=None):
        if myname is not None and mymessage is not None:
            self.call_service("logbook/log", name=f"{myname} :", message=f"{mymessage}")
            
    def get_temp_entity(self, entity, myattribute=None):
        if myattribute is None:
            entity_state = self.get_state(entity)
        else:
            entity_state = self.get_state(entity, attribute=myattribute)
        if entity_state not in [None, "unknown", "unavailable"]:
            return float(entity_state)
        else:
            self.log(f" For {entity} the temperature is '{entity_state}'")
            self.log(" Returning nominal value of 18 degrees")
            return 18

    def winter_time(self):
        dt = datetime.datetime.today()
        month = dt.month
        if month in [1, 2, 3, 4, 5, 9, 10, 11, 12]:
            return True
        else:
            return False

    def average_temp(self, entity_list):
        temp_list = []
        for entity in entity_list:
            temp_list.append(self.get_temp_entity(entity))
        return self.average(temp_list)

    def upper_average_temp(self, entity_list):
        temp_list = []
        for entity in entity_list:
            temp_list.append(self.get_temp_entity(entity))
        average = self.average(temp_list)
        max_temp = max(temp_list)
        return round(0.5 * (average + max_temp), 1)

    def get_average_outside_temp(self):
        return self.average_temp(self.outside_entity)
            
    def get_average_upstairs_temp(self):
        return self.upper_average_temp(self.upstairs_entity)

    def get_average_downstairs_temp(self):
        return self.average_temp(self.downstairs_entity)
        
    def calc_set_temp(self):
        manual = self.get_state("input_boolean.manual_thermostat")
        if manual == r'off':
            outside_temp = self.get_average_outside_temp()
            self.logbook("outside mean temp", outside_temp)
            current_set_temp = self.get_temp_entity(self.thermostat, myattribute="temperature")
            self.logbook("pre-set temp", current_set_temp)
            set_temp_hallway = self.get_temp_set_value()
            return set_temp_hallway
        else:
            return None

    def get_temp_set_value(self):
        use_upstairs = False
        temp_upstairs = self.get_average_upstairs_temp()
        self.logbook("upstairs average temp", temp_upstairs)
        if self.now_is_between("21:05:00", "10:29:59"):
            use_upstairs = True
        set_temp_hallway = float(self.args["off_temp"])
        outside_temp = self.get_average_outside_temp()
        if outside_temp <= 13.5:
            if not use_upstairs:
                set_temp_hallway = self.get_downstairs_set_temp()
            elif use_upstairs:
                if temp_upstairs >= 21.5:
                    return set_temp_hallway
                set_temp_hallway = self.get_upstairs_set_temp()
        return set_temp_hallway

    def get_downstairs_set_temp(self):
        temp_hallway = self.get_average_downstairs_temp()
        self.logbook("current hallway temp", temp_hallway)
        set_temp_hallway = None
        offset = -1 # for summer
        is_winter_time = self.winter_time()
        if is_winter_time:
            offset = 0
        if 19 <= temp_hallway < 20:
            set_temp_hallway = 19.5
        elif 18 <= temp_hallway < 19:
            set_temp_hallway = 20
        elif temp_hallway >= 20:
            set_temp_hallway = 18.5
        elif temp_hallway < 18:
            set_temp_hallway = 20.5
        return set_temp_hallway + offset

    def get_upstairs_set_temp(self):
        temp_upstairs = self.get_average_upstairs_temp()
        set_temp_hallway = None
        offset = -2 # for summer
        is_winter_time = self.winter_time()
        if is_winter_time:
            offset = 0
        if temp_upstairs >= 21:
            set_temp_hallway = 17.5
        elif temp_upstairs >= 19.5:
            set_temp_hallway = 18
        elif temp_upstairs >= 19:
            set_temp_hallway = 18.5
        elif temp_upstairs < 19:
            set_temp_hallway = 19
        return set_temp_hallway
        
    def is_somebody_home(self):
        daddy = self.get_state("device_tracker.rob_lan")
        mammy = self.get_state("device_tracker.fabi_lan")
        if daddy == r'home' or mammy == r'home':
            return True
        elif daddy == r'not_home' and mammy == r'not_home':
            return False
        
                
    def evening(self, kwargs):
        manual = self.get_state("input_boolean.manual_thermostat")
        if manual == r'off':
            is_home = self.is_somebody_home()
            if not is_home:
                self.set_heat_temp()
                
    def bedtime(self, kwargs):
        self.turn_off_heat()
            
    def morning(self, kwargs):
        is_home = self.is_somebody_home()
        if is_home:
            self.set_heat_temp()
        else:
            self.turn_off_heat()
            
    def heat_check(self, kwargs):
        is_home = self.is_somebody_home()
        if is_home:          
            self.set_heat_temp()
        else:
            self.turn_off_heat()
            
    def switch(self, entity, attribute, old, new, kwargs):
        if new == "off":
            self.turn_off_heat()
        elif new == "on":
            self.set_heat_temp()
            
    def set_heat_temp(self):
        hot_water_state = self.get_state(self.hot_water_entity)
        if hot_water_state != r'on':
            current_set_temp = self.get_temp_entity(self.thermostat, myattribute="temperature")
            set_temp_calc = self.calc_set_temp()
            if set_temp_calc is not None:
                if current_set_temp != set_temp_calc:
                    self.call_service("climate/set_temperature", entity_id = self.thermostat, 
                    temperature = set_temp_calc)
                    self.logbook("calculated set temp", set_temp_calc)
        elif hot_water_state == r'on':
            self.log("hot water on, not adjusting heat")
            self.logbook("hot water is", hot_water_state)
            
    def turn_off_heat_kwargs(self, kwargs):
        self.turn_off_heat()
        
    def turn_off_heat(self):
        manual = self.get_state("input_boolean.manual_thermostat")
        if manual == r'off':
            current_set_temp = self.get_state(self.thermostat, attribute="temperature")
            if float(current_set_temp) != float(self.args["off_temp"]):
                self.call_service("climate/set_temperature", entity_id = self.thermostat, 
                temperature = self.args["off_temp"])
                self.logbook("smart temp", "turning OFF heat")
        
    def boost(self, kwargs):
        manual = self.get_state("input_boolean.manual_thermostat")
        if manual == r'off':
            is_home = self.is_somebody_home()
            if is_home:
                self.set_heat_temp()
                self.run_in(self.turn_off_heat_kwargs, self.boost_duration_sec)
