// projects-data.js
// Static project data - manually curated from pictures/* folders
// Last updated: 2026-05-19

window.PROJECTS = [
  {
    id: "fin-glassbox",
    title: "fin-glassbox",
    subtitle: ["Technology & Data Science", "Quantitative Finance"],
    description: "An explainable multimodal neural framework for financial risk management that decomposes market decision-making into specialised modules combining temporal market encoders, FinBERT financial text analysis, graph neural networks for contagion risk, and classical financial risk measures. Features full system XAI traces and risk-constrained fusion with interpretable position sizing.",
    tags: ["finance", "neural-framework", "gnn", "lstm", "risk-management", "finbert", "market-analysis", "xai", "multi-modal"],
    domain: ["risk", "finance", "tech"],
    image: "pictures/fin-glassbox/fin-glassbox2.png",
    repo: "https://github.com/ib-hussain/fin-glassbox",
    live: "https://ib-hussain.github.io/fin-glassbox/"
  },
  {
    id: "writers-block",
    title: "Writer's Block",
    subtitle: ["Marketing & Risk Prediction", "Technology & Data Science", "Healthcare AI"],
    description: "AI-powered blog generation platform for legal & health content creators using parallel specialised agents and a compiler stage. Features reliability mechanisms (fallbacks, retries), structured PostgreSQL-backed content management, and cost-optimized multi-model architecture (~$0.04 per blog).",
    tags: ["nlp", "agents", "postgres", "flask", "marketing", "content-ai", "llm-orchestration"],
    domain: ["risk", "tech", "health"],
    image: "pictures/writers-block/WritersBlock.png",
    repo: "https://github.com/ib-hussain/writers-block",
    live: "https://writers-block-weup.onrender.com"
  },
  {
    id: "neohacks",
    title: "Multi-Omics Cancer Detector",
    subtitle: ["Healthcare AI", "Technology & Data Science"],
    description: "Developed an integrative machine learning model to classify Head and Neck Cancer (HNC) stages and predict risk factors using multi-omics data (genomics, epigenomics, transcriptomics) and histopathology images. Built end-to-end in under 24 hours, combining high-dimensional biomedical data with rigorous feature engineering to address real-world clinical challenges.",
    tags: ["healthcare-ai", "epigenetics", "pathology", "methylation", "machine-learning", "biomedical", "multi-modal"],
    domain: ["health", "tech"],
    image: "pictures/NeoHacks/histopathology.png",
    repo: "https://github.com/ib-hussain/TCGA-Integrative-Analysis",
    live: "https://ib-hussain.github.io/TCGA-Integrative-Analysis/"
  },
  {
    id: "secret-to-happiness",
    title: "The Secret to Happiness",
    subtitle: ["Technology & Data Science", "Marketing & Risk Prediction"],
    description: "Multi-dimensional investigation into the structural determinants of global happiness across 150+ countries using 13 years of data (2011–2023). Features an end-to-end data engineering pipeline to merge 12+ international datasets (World Bank, OWID), statistical feature engineering, and high-dimensional visual analytics to explore economic thresholds, governance quality, and shifting human needs.",
    tags: ["data-engineering", "data-visualization", "python", "pandas"],
    domain: ["tech", "risk"],
    image: "pictures/secret_to_happiness/Choropleth Map Global Happiness Score Distribution.png",
    repo: "https://github.com/ib-hussain/secret_to_happiness",
    live: "https://ib-hussain.github.io/secret_to_happiness/"
  },
  {
    id: "disaster-recovery-analysis",
    title: "Disaster Recovery Analysis",
    subtitle: ["Marketing & Risk Prediction", "Technology & Data Science"],
    description: "Data-driven framework measuring national disaster resilience using multisource global datasets. Developed the Resilience Recovery Score (RRS) by integrating disaster events, macroeconomic growth, and socio-institutional variables. Features interactive dashboards, global resilience mapping, and an end-to-end data pipeline mapping out the disproportionate leverage of modern governance capacity on recovery.",
    tags: ["data-science", "data-visualization", "macroeconomics", "resilience-analytics"],
    domain: ["risk", "tech"],
    image: "pictures/disaster-recovery-analysis/dashboard4.png",
    repo: "https://github.com/ib-hussain/disaster-recovery-analysis",
    live: "https://ib-hussain.github.io/disaster-recovery-analysis/"
  },
  {
    id: "multi-agentic-health-assistant",
    title: "Multi-Agentic Health Assistant",
    subtitle: ["Healthcare AI", "Technology & Data Science"],
    description: "An innovative wellness platform combining multiple Large Language Models (LLMs) and vision models to provide personalized support for physical and mental well-being. Features three specialised AI agents for diet tracking, exercise planning, and mental health support with persistent memory using PostgreSQL & Pinecone.",
    tags: ["healthcare-ai", "agents", "postgres", "vector-db", "vision", "llm", "multi-modal", "flask"],
    domain: ["health", "tech"],
    image: "pictures/Multi-Agentic_Health_Assistant/virtualhealth.png",
    repo: "https://github.com/ib-hussain/Multi-Agentic_Health_Assistant",
    live: "https://multi-agentic-health-assistant.onrender.com"
  },
  {
    id: "statistical-analysis",
    title: "Inflation Dynamics for Pakistan",
    subtitle: ["Quantitative Finance", "Technology & Data Science", "Marketing & Risk Prediction"],
    description: "Advanced statistical analysis of Pakistan's inflation using annual macroeconomic data (1980–2023) with 2024 forecast. Analyzed inflation drivers using ARIMA and regularised regression (Ridge/Lasso/Elastic Net), comparing models with AIC/MSE/RMSE and applying statistical tests to identify significant factors.",
    tags: ["finance", "timeseries", "arima", "regression", "forecasting", "econometrics", "statistics"],
    domain: ["finance", "tech", "risk"],
    image: "pictures/Statistical Analysis/Statistical Analysis.png",
    repo: "https://github.com/ib-hussain/Projects.py/tree/main/Statistical%20Analysis",
    live: "https://ib-hussain.github.io/Projects.py/Statistical%20Analysis/"
  },
  {
    id: "movie-genre-detection",
    title: "Movie Genre Detection Model",
    subtitle: ["Technology & Data Science"],
    // also make this for marketing domain as it has applications in movie marketing and recommendation systems
    // and also applicaions in finance
    description: "Multi-label classification system to detect movie genres by analyzing YouTube trailer transcripts using NLP techniques. Features include speech-to-text transcription with Google's ASR, n-gram extraction, supervised learning with logistic regression, and evaluation using micro/macro F1-score and mean average precision.",
    tags: ["nlp", "machine-learning", "classification", "asr", "python"],
    domain: ["tech"],
    image: "pictures/Movie-Genre-Detection-Model/movie-genre-detection-model.png",
    repo: "https://github.com/ib-hussain/Movie-Genre-Detection-Model",
    live: ""
  },
  {
    id: "3moviecollectors",
    title: "3movieCollectors",
    subtitle: ["Technology & Data Science"],
    description: "Comprehensive movie community web application with social features, movie catalog, and advanced admin management system. Features include friend system, messaging, watch events, discussion posts, real-time notifications, admin dashboard with Chart.js visualizations, content moderation, audit logging, and comprehensive security monitoring.",
    tags: ["web", "nodejs", "mysql", "full-stack", "admin-panel", "social-features"],
    domain: ["tech"],
    image: "pictures/3movieCollectors/3movCollectors.png",
    repo: "https://github.com/ib-hussain/3movieCollectors",
    live: ""
  },
  {
    id: "network-emulator",
    title: "Network Emulator",
    subtitle: ["Technology & Data Science"],
    description: "Simulates a computer network consisting of routers and end machines with message routing across multiple hops. Features include binary heap priority queues, FIFO queue management, dynamic routing table updates, Dijkstra's algorithm for path finding, and traceable message routing.",
    tags: ["cpp", "algorithms", "networking", "data-structures", "dijkstra"],
    domain: ["tech"],
    image: "pictures/Network-Emulator/network_emulaotr.jpg",
    repo: "https://github.com/ib-hussain/Network-Emulator",
    live: ""
  },
  // {
  //   id: "python-projects",
  //   title: "Python Projects",
  //   subtitle: ["Technology & Data Science"],
  //   // this is also for finance and marketing domains as it has applications in financial data analysis, marketing analytics, and general data science
  //   description: "Collection of Python-based projects focusing on data cleaning, statistical analysis, basic machine learning, Natural Language Processing (NLP), and Computer Vision (CV). Includes multilingual NLP (Urdu text processing), hypothesis testing, regression models, probabilistic inflation prediction, and image processing with OpenCV.",
  //   tags: ["python", "nlp", "machine-learning", "opencv", "statistics", "data-science"],
  //   domain: ["tech"],
  //   image: "pictures/Projects.py/python.jpg",
  //   repo: "https://github.com/ib-hussain/Projects.py",
  //   live: "https://ib-hussain.github.io/Projects.py/"
  // },
  {
    id: "cinemago",
    title: "Cinemago",
    subtitle: ["Technology & Data Science"],
    description: "A movie discovery and rating platform built using Flask. Users can browse, rate, and suggest movies. Admins can add new content via web scraping. Features weighted rating system, user classification, admin dashboard, and SQLite database with community suggestions.",
    tags: ["web", "flask", "sqlite", "web-scraping", "full-stack"],
    domain: ["tech"],
    image: "pictures/Cinemago/cinemago_light.png",
    // use the above on light mode and the below on dark mode for better visibility
    // pictures\Cinemago\cinemago_dark.png
    repo: "https://github.com/ib-hussain/Cinemago",
    live: "https://cinemago-2u2f.onrender.com/"
  },
  {
    id: "gameboy",
    title: "GameBoy",
    subtitle: ["Technology & Data Science"],
    description: "A lightweight C++ collection of classic games (Snake, Wordle, Hangman) built with simplicity, logic, and fun in mind. Features OOP design, interactive GUI with real-time feedback, score tracking, and modular architecture for easy extension.",
    tags: ["cpp", "oop", "games", "gui"],
    domain: ["tech"],
    image: "pictures/GameBoy/gameboy.jpeg",
    repo: "https://github.com/ib-hussain/GameBoy",
    live: ""
  },
  {
    id: "game-of-life",
    title: "Conway's Game of Life",
    subtitle: ["Technology & Data Science"],
    description: "A C++ implementation of Conway's Game of Life, simulating the evolution of cellular automata based on simple rules. Features terminal-based grid visualisation, real-time cell evolution, efficient array-based updates, and clean beginner-friendly structure exploring algorithms and grid manipulation.",
    tags: ["cpp", "algorithms", "simulation", "cellular-automata"],
    domain: ["tech"],
    image: "pictures/Game-Of-Life/game-of-life.gif",
    repo: "https://github.com/ib-hussain/Game-Of-Life",
    live: ""
  }
];

// Domain filter configuration
// make this such that 1 object can have multiple domains and the filter will show projects that match any of the selected domains
window.PROJECT_DOMAINS = [
  { key: "all", label: "All Projects" },
  { key: "health", label: "Healthcare AI" },
  { key: "finance", label: "Quantitative Finance" },
  { key: "risk", label: "Marketing & Risk Prediction" },
  { key: "tech", label: "Technology & Data Science" }
];
