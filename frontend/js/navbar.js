// /js/navbar.js
document.addEventListener("DOMContentLoaded", function () {
    fetch("navbar.html")
        .then(response => response.text())
        .then(data => {
            const navContainer = document.createElement("div");
            navContainer.innerHTML = data;
            document.body.insertBefore(navContainer, document.body.firstChild);

            // Add scroll behavior for navbar
            // window.addEventListener("scroll", function() {
            //     const navbar = document.querySelector(".navbar");
            //     if (window.scrollY > 10) {
            //         navbar.classList.add("scrolled");
            //     } else {
            //         navbar.classList.remove("scrolled");
            //     }
            // });

            // Improved active page detection
            const currentPage = getCurrentPage();
            document.querySelectorAll("[data-page]").forEach(el => {
                const pageName = el.getAttribute("data-page");
                if (pageName === currentPage) {
                    el.classList.add("active");
                }
            });
        })
        .catch(error => {
            console.error("Error loading navbar:", error);
        });
    // Helper function to get current page name
    function getCurrentPage() {
        const path = window.location.pathname;
        const page = path.split("/").pop().split(".")[0];
        
        // Map file names to data-page values if they don't match
        const pageMap = {
            'chatbot': 'chatbot',
            'databaseView': 'dbOverview',
            'db_promptdata': 'dbPromptData',
            'db_blogparts': 'dbBlogParts',
            'db_progress': 'dbProgress',
            'profile': 'profile'
        };

        return pageMap[page] || page;
    }
});