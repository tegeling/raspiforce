###############################################################################
##                                                                           ##
##   raspiforce project                                                      ##
##   Use Raspberry Pi to simulate IoT sensor reading and automated case      ##
##   creation in Salesforce Service Cloud                                    ##
##                                                                           ##
##   Use --simulation as commandline parameter to execute without            ##
##   Raspberry Pi connected and simulate asset and case creation             ##
##                                                                           ##
##   Use --chat as commandline parameter to publish status messages          ##
##   to the Websocket Chat server                                            ##
##                                                                           ##
##   See GitHub project for more details:                                    ##
##   https://github.com/tegeling/raspiforce                                  ##
##                                                                           ##
##   Thomas Egeling                                                          ##
##   tegeling@salesforce.com                                                 ##
##                                                                           ##
###############################################################################

from simple_salesforce import Salesforce
from websocket import create_connection
import json
import ConfigParser
import time
import os
import glob
import sys

#
# Define the celsius temperature threshold to raise alarms and create a new support case
# Set a default value that can be replaced by configuration settings in the setup Salesforce org
#
global alarm_threshold_default
alarm_threshold_default = 25

#
# Sleep in seconds to allow cooldown of the temperature
#
global sleep_reset
sleep_reset = 60

def print_msg():
	if chat_mode:
		print 'Program is running in chat mode...'
	if simulation_mode:
		print 'Program is running in simulation mode...'
	else:
		print 'Program is running'
		print 'Please press Ctrl+C to end the program...'


def destroy():   # When program ending, the function is executed. 
	if not simulation_mode:
		GPIO.cleanup()
	if chat_mode:
		ws.close()
	print "Exit."

def chat(handle, msg):
	global ws
	#
	# Send new chat message to monitoring service via websockets
	#
	myText = u'{"handle": "' + handle + '","text": "' + msg + '"}'
	myjson = json.loads(myText)
	payload = json.dumps(myjson, ensure_ascii = False).encode('utf8')
	ws.send(payload)

def setup():
	#
	# Declare global variables
	#
	global myRegId
	global myUsername
	global myPassword
	global myToken
	global ownerid
	global accountid
	global contactid
	global assetid
	global assetprefix
	global assetdesc
	global alarm_threshold
	global status
	global subject
	global case_type
	global ws

	#
	# setup Raspberry Pi DS18b20 device file
	# see https://cdn-learn.adafruit.com/downloads/pdf/adafruits-raspberry-pi-lesson-11-ds18b20-temperature-sensing.pdf
	#
	if not simulation_mode:
		global device_file
		os.system('modprobe w1-gpio')
		os.system('modprobe w1-therm')
		base_dir = '/sys/bus/w1/devices/'
		device_folder = glob.glob(base_dir + '28*')[0]
		device_file = device_folder + '/w1_slave'

	#
	# Read configuration from file
	#
	config = ConfigParser.RawConfigParser()
	config.read('salesforce_login.cfg')

	#
	# Establish Websockt connection for monitoring chat service
	#
	if chat_mode:
		ws_url = config.get('Chat', 'ws_url')
		ws = create_connection(ws_url)


	#
	# Lookup Salesforce demo org credentials and configuration
	#
	sf_lookup = Salesforce(username=config.get('Salesforce', 'username'), password=config.get('Salesforce', 'password'), security_token=config.get('Salesforce', 'security_token'))
	result = sf_lookup.query("SELECT Id, Username__c, Password__c, Security_Token__c, Case_Owner__c, Case_Account_Id__c, Case_Contact_Id__c, Case_Asset_Id__c, Asset_Prefix__c, Case_Status__c, Case_Type__c, Case_Subject__c, Alarm_Threshold__c, Asset_Description__c FROM Raspberry_Pi_Demo__c WHERE Active__c = true AND Raspi_Hostname__c = " + config.get('Host', 'hostname'))

	#
	# Register new demo run
	#
	myRegId = result.get('records')[0].get('Id')	
	sf_lookup.Raspberry_Pi_Demo_Registration__c.create({'Raspberry_Pi_Demo__c':myRegId,'Status__c':'connected'})

	myUsername = result.get('records')[0].get('Username__c')
	myPassword =  result.get('records')[0].get('Password__c')
	myToken = result.get('records')[0].get('Security_Token__c')

	ownerid = result.get('records')[0].get('Case_Owner__c')
	accountid = result.get('records')[0].get('Case_Account_Id__c')
	contactid = result.get('records')[0].get('Case_Contact_Id__c')
	assetid = result.get('records')[0].get('Case_Asset_Id__c')
	assetprefix = result.get('records')[0].get('Asset_Prefix__c')
	assetdesc = result.get('records')[0].get('Asset_Description__c')
	alarm_threshold = result.get('records')[0].get('Alarm_Threshold__c')
	status = result.get('records')[0].get('Case_Status__c')
	subject = result.get('records')[0].get('Case_Subject__c')
	case_type = result.get('records')[0].get('Case_Type__c')

	if chat_mode:
		chat("Setup","Connection established.")
	#
	# Check the OwnerId, AccountId and ContactId if they are empty and set to None
	#
	if ownerid is None:
	   print "OwnerId is empty"
	   ownerid = ""

	if accountid is None:
	   print "AccountId is empty"
	   accountid = ""

	if contactid is None:
	   print "ContactId is empty"
	   contactid = ""

	if alarm_threshold is None:
	   alarm_threshold = alarm_threshold_default

def read_temp_raw():
	#
	# Read and return lines from device file
	#
	f = open(device_file, 'r')
	lines = f.readlines()
	f.close()
	return lines

def read_temp():
	#
	# Read temperature from device file
	#
	lines = read_temp_raw()
	#
	# Ignore the first sample
	#
	lines = read_temp_raw()

	while lines[0].strip()[-3:] != 'YES':
		time.sleep(0.2)
		lines = read_temp_raw()
	equals_pos = lines[1].find('t=')
	if equals_pos != -1:
		temp_string = lines[1][equals_pos+2:]
		temp_c = float(temp_string) / 1000.0
	return temp_c

def loop():
	#
	# Create new connection to demo org
	#
	sf = Salesforce(username=myUsername, password=myPassword, security_token=myToken)

	#
	# Create new asset
	#
	global assetid
	if assetid is None:
		newassetname = assetprefix + "-" + time.strftime("%Y%m%d_%H%M%S")
		newasset = sf.Asset.create({'Name':newassetname,'AccountId':accountid,'ContactId':contactid,'Description':assetdesc})
		assetid = newasset.get('id')
		if chat_mode:
			chat(newassetname,"Asset created.")
	else:
		assetidquoted = "'" + assetid + "'"
		assetresult = sf.query("SELECT Name FROM Asset WHERE Id = " + assetidquoted)
		newassetname = assetresult.get('records')[0].get('Name')
		if chat_mode:
			chat(newassetname,"Asset found.")


	##
	## Infinite loop to allow reset of temperature
	##
	while True and not simulation_mode:
		#
		# Loop the device and check the temperature
		#
		alarm = False
		while not alarm:
			currenttemp = read_temp()
			print currenttemp
			if chat_mode:
				chat(newassetname, "Temperature Celsius: " + str(currenttemp))
			if currenttemp > alarm_threshold:
				print "Temperature Alarm!"
				if chat_mode:
					chat(newassetname, "Temperature Alarm! ")
				alarm = True
			time.sleep(2)

		#
		# Create new case and sleep a while to allow temperature to cool down
		#
		sf.Case.create({'Subject':subject,'Status':status,'OwnerId':ownerid,'AccountId':accountid,'ContactId':contactid,'AssetId':str(assetid),'Type':case_type})
		if chat_mode:
			chat(newassetname, "Case created.")
		print "Sleep for " + str(sleep_reset) + " seconds..."
		if chat_mode:
			chat(newassetname, "Sleep for " + str(sleep_reset) + " seconds...")
		time.sleep(sleep_reset)

	#
	# Simulate new case 
	#
	if simulation_mode:
		sf.Case.create({'Subject':subject,'Status':status,'OwnerId':ownerid,'AccountId':accountid,'ContactId':contactid,'AssetId':str(assetid),'Type':case_type})
		if chat_mode:
			chat(newassetname, "Case simulated.")

if __name__ == '__main__': # Program starting from here 
	global simulation_mode
	global chat_mode
	simulation_mode = False
	chat_mode = False
	global ws

	if (len(sys.argv) == 2) and (str(sys.argv[1]) == "--simulation"):
		simulation_mode = True
	if (len(sys.argv) == 2) and (str(sys.argv[1]) == "--chat"):
		chat_mode = True
	if (len(sys.argv) == 3) and (str(sys.argv[1]) == "--simulation") and (str(sys.argv[2]) == "--chat"):
		chat_mode = True
		simulation_mode = True
	if (len(sys.argv) == 3) and (str(sys.argv[1]) == "--chat") and (str(sys.argv[2]) == "--simulation"):
		chat_mode = True
		simulation_mode = True
	print_msg()
	setup() 
	try:
		loop()
	except KeyboardInterrupt:  
		destroy()  
