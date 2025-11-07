---

# **✉️ Guided Bulk Mail Merge Sender**

A powerful, customizable, and user-friendly **Streamlit application** designed for running mail merge campaigns. This app provides a five-step guided workflow to handle data mapping, HTML template editing, personalized previews, SMTP configuration, and real-time sending status tracking.

---

## **✨ Features**

* **5-Step Guided Workflow:** A clear, linear process to ensure all configurations are correctly set before sending (Data, Template, Preview, SMTP, Send).  
* **Flexible Data Input:** Upload a **CSV file** for rich personalization or enter a simple, **comma-separated list of emails**.  
* **Custom Variable Mapping:** Easily define short, user-friendly placeholders (e.g., ```{{Name}}```) for your long CSV column names.  
* **Template Editor with Placeholder Helper:** Upload and edit your HTML template directly within the app, with a visible list of available ```{{Placeholders}}``` for easy copying and insertion.  
* **Personalized Record Preview:** Verify exactly how the email and subject line will look for any specific recipient record before starting the bulk send.  
* **Secure SMTP Configuration:** Configure your email server details (SMTP Server, Port, Sender Email, App Password/Token) and run a **live test** to confirm authentication before sending.  
* **Concurrent Sending:** Utilizes multi-threading with configurable worker count for faster bulk delivery.  
* **Real-time Status Tracking:** Monitor the progress of every email with statuses like ```Sent```, ```Failed```, ```Invalid Email```, and ```Authentication Error```.

---

## **⚙️ Prerequisites**

You will need **Python (3.8+)** installed on your system, along with the required libraries.

* ```python \>= 3.8```  
* ```streamlit```  
* ```pandas```  
* ```python-dotenv```  
* ```email-validator```

---

## **🚀 Setup and Installation**

### **1\. Clone the Repository**

```
git clone https://github.com/your-username/bulk-mail-merge-sender.git  
cd bulk-mail-merge-sender
```

### **2\. Create a Virtual Environment (Recommended)**

```
python \-m venv venv  
source venv/bin/activate  \# On Linux/macOS  
\# .\\venv\\Scripts\\activate   \# On Windows
```

### **3\. Install Dependencies**

```
pip install \-r requirements.txt   
\# Or manually: pip install streamlit pandas python-dotenv email-validator
```

### **4\. Configure Environment Variables**

For security, the application uses a ```.env``` file to manage sensitive credentials (though the user inputs them in the UI, this is good practice for the app development environment).

Create a file named ```.env``` in the root directory of the project.

The application will open in your web browser, typically at ```http://localhost:8501```.

### **2\. Follow the 5-Step Guided Workflow**

Navigate through the steps using the **"Next"** and **"Previous"** buttons at the bottom of the page.

#### **Step 1: Data & Mapping**

1. **Upload Data:** Upload your **CSV file** or paste a comma-separated list of emails.  
2. **Select Recipient Column:** Choose the CSV column containing the primary email addresses.  
3. **Define Subject/From:** Set the sender name and the email subject line (which can also include personalized variables).  
4. **Variable Mapping:** Define concise, unique placeholders (e.g., ```Name```, ```OrderID```) for the corresponding CSV columns.

#### **Step 2: Template Editor**

1. **Upload Template:** Upload your email content as an **HTML file**.  
2. **Edit Content:** Use the editor to insert the ```{{Placeholders}}``` you defined in Step 1\. The list of available placeholders is displayed on the side for easy reference.  
3. Check the un-personalized preview below the editor.

#### **Step 3: Record Preview**

1. Enter a **Record ID** (row index) from your dataset.  
2. Click **"Generate Personalized Preview"** to see the final, merged email content and subject line for that specific recipient.

#### **Step 4: SMTP & Test**

1. **Enter Credentials:** Provide your SMTP server details, including the server address (e.g., ```smtp.gmail.com```), port (e.g., ```587```), your sender email, and the **App Password/Token**.  
2. **Configure Threads/Retries:** Adjust the number of concurrent worker threads and retries on failure.  
3. Click **"Test SMTP Connection"** to confirm your credentials are valid and the server connection works.

#### **Step 5: Send & Status**

1. Once all checks pass, click **"Start Bulk Send"**.  
2. The application will begin processing, and you will see a **real-time status table** showing the result of every email attempt (```Sent```, ```Failed```, ```Authentication Error```, etc.).

---

## **⚠️ Important Notes on SMTP**

* **App Passwords:** If you are using services like **Gmail** or **Outlook**, you must generate and use a secure **App Password** or an OAuth token. Standard account passwords will often fail due to modern security protocols.  
* **Rate Limits:** Be aware that most email providers have strict limits on the number of emails you can send per hour or per day. Configure your **Concurrent Workers** appropriately to avoid being blocked.
