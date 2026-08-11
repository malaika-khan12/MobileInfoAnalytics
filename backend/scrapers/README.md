

We will be using Playwright with python for web scraping.

This folder contains files that will help in scraping of a single product page. Each file in this folder is the name of a site that we will scrap. According to the template of the html of a site each file will be different but basic schema is that each file will have 1 class. The class will help in scraping of that product page accoridng to the template. The `scrapers/` folder will have all files with 1 class each which will be in a header format. The files and functions of this folder need to also be like that. All of it needs to be like header files because we will import and use everything in the `navigation_to_page/` folder where the main full scraping logic lies. 

For initial making and testing we will need to use the scraper files in non-header way and write code that needs to be tested using basic methods like it takes a url and a html tag address and scrapes the data from it and outputs it and that is how we know it is working. After that we will convert it into header format and use it in the frontend folder. 