This entire folder contains html, css, js from 2 different small websites made by me. They have been added in this folder to make you understand how the UI for the website needs to be.

A consistent color pallette needs to be used for the entire site.

### The comprehensive color and css base definitions and the most important color defintiions are in `frontend/css/base-styles.css` file. This file is like the abstract class for all other css files. They are all children of this css file.

### The entire site needs to use `frontend/media/favicon.ico` & `frontend/media/favicon.png` as the logos(and even in foooter and navbar) and the favicon for the page in the headers.

### For all places where there will be loading, we will be using `frontend/media/loading.gif` for loading.

### Rest everywhere the names of the file's in the `frontend/media/` folder are quite self explanatory.

# navbar
### info:
the following should be the options available in it:
- scrapers
- admin panel
- database view
- dashboard
- real time analytics

Each of these is a whole side of the website not just a single page.

## layout
you need to take inspiration for it from the navbar of the ib-hussain.github.io website. It's files are included in this repository and you will identify them with ease. They are all related with each other and are for my portfolio site. The colours should be taken from the abstract class. The layout and the css styling inspiration should also be taken from my portfolio site.

# footer
### info
footer will be displayed on only these sides of the website:
- admin panel
- real time analytics

## layout 
I do not know know what to put in it yet although you have the entire repository's context and our frontend's purpose to consider for making the footer. You already know what colors to use. There is also inspiration for you in this folder for design. 

# scrapers
### info
This side of the site will have further 5 child nodes:
- mymobile.pk
- www.daraz.pk
- www.gsmarena.com
- www.mega.pk
- www.whatamobile.com.pk
- www.whatmobile.com.pk

Each of these pages will present the user with different options:
- scrap a single page(will require user to give URL)
- scrap multiple pages(will require user to give multiple URL's)
- scrap a number of page(give minimum or maximum number of pages to scrap, otherwise the minimum=1, max=15)
- scrap a whole website, which means the minimum=1 but maximum is all pages on that site. (This options doesnot have a display json option.)

Each of these options have a few options into them as well:
- show scraped as json (last one doesnot have this option)
- store scraped into json 
- store scraped into json then database and keep json
- store directly into database

## layout
The layout here is entirely upto you. you need to properly show the json files on the pages, manage memory usage and erro handling of any sort. You need to properly handle all UI elements and UI html rendering. Make the UI good for UX. It needs to look good and be functional as well. Use best design principles. take insiration if you have to from the alreayd present files in this folder.

# admin panel
### info 
For this I have not thought alot but for the initial phase of this I need it to have a whole ass space for typing SQL statememnts and executing them and seeing status. It should also allow the admin to view tables through sql statement execution. It need to be connected to any backend database we are going to be using, be it Azure/Microsoft Fabric/AWS Redshift or local Postgres database.

## layout
Make the best possible layout for this page. The SQL typing space needs to be beautiful and properly rendered.The SQL Table views need to be shown properly. They need to be well rendered and have no problem. The entire UI of this site including this site needs to be industrial production quality.

# database view
### info 
This is for any user to see any table of the database. This is basically a view site. At maximum a user can view any 2 tables of the database on the page otherwise default is 1 table on the page. The user can at maximum only see 100 rows of a table, for more they have to go to the next page.

## layout
take inspiration for the layout from production quality industrial designs that serve the same purpose or take inspiration from the files in this folder.

# dashboard
### info 
For the first phase of this, m basic idea is that I want the database analytics to be shown in streamlit so if it's possible, this side of the site to be rendered and made entirely in streamlit. Although we also have the option of D3.js and showing python visualisations using flask if that's possible. Implement what seems possible but keep my preferences infront of you. The visualisations for this side of the page and its style and structure will be later dictated to you but for now make an initial design of that side of the site and if possible keep the main navbar rendered on this side of the site as well so the entire site looks connected.

## layout
Your choice. Take inspiration from `frontend/telecom_churn_dashboard.py` file as it shows a pretty good streamlit dashboard although different colours. Please keep a consistent, corporate and beautifully grounded colour pallete for the dashboard.

# real time analytics
The layout and information for this side of the site will be very similar to the `dashboard` part but this side will make visualisations entirely in D3.js . This side of the analytics will be more focused towards the time-series aspect as well as the over time change in data and analysing it over time. This will also use the same color pallete as the main dashboard. This needs to be almost identical to the main dashboard except present a different look with regards to the different aspect of data it aims to show. Aim for production quality visualisations and layouts.