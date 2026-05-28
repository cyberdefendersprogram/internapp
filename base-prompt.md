I want to make an intern app which is similar to classapp in the location
  /Users/vaibhavb/Documents/GitHub/classapp, it will be deployed on the same server and the
  student list will come from a google sheet. However the data model is completely different and
  its meant to enable tracking and working of students for a summer internship which is described
  in details at this page /Users/vaibhavb/Documents/GitHub/www-homepage/pages/intern.html. I want
  use to use this to plan on implementing the app and clarify requirements. It will be a docker
  image drive app, with make files and auth data in local sqlite but other data in google sheet.
  The student data model will be similar as roster and overtime we will add information for each
  of the tracks. The tracks are details in intern.html with a employer sponsor and their email --
  however this will change so we can fetch the tracks from google spreadsheet. Now work on
  clarifying the requirements before we build it.

  Email is sent via the ForwardEmail REST API (https://api.forwardemail.net/v1/emails).
  Credentials are set via FORWARDEMAIL_USER (sending address) and FORWARDEMAIL_PASS (API key)
  environment variables. SMTP is not used.
