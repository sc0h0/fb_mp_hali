from playwright.sync_api import sync_playwright, TimeoutError 
from openai import OpenAI
import datetime
import os
import pytz
import glob
from bs4 import BeautifulSoup

from alert import send_alert_email


screenshot_mode = False
print_mode = True

tz_aet = pytz.timezone('Australia/Sydney')  # 'Australia/Sydney' will automatically handle AEST/AEDT

# Determine the base path relative to the script's location
base_path = os.path.dirname(os.path.abspath(__file__))

# Define the path to the 'data' directory
extracted_folder_path = os.path.join(base_path, '..', 'data/extracted_id')
visited_folder_path = os.path.join(base_path, '..', 'data/visited_id')
matched_folder_path = os.path.join(base_path, '..', 'data/matched_id')
screenshot_path = os.path.join(base_path, '..', 'screenshots')

eid_csv_files = glob.glob(os.path.join(extracted_folder_path, '*.csv'))
vid_csv_files = glob.glob(os.path.join(visited_folder_path, '*.csv'))
mid_csv_files = glob.glob(os.path.join(matched_folder_path, '*.csv'))




def details_are_exclude(details_collected_text):
    # Convert the collected text to lowercase for case-insensitive comparison
    text_lower = details_collected_text.lower()
    # enter any keywords with 'abc', 'xyz' that you want excluded
    keywords = ['abc', 'xyz']
    # Check if the lowercase text contains
    return any(keyword in text_lower for keyword in keywords)
    
def heading_details_keyword(details_collected_text, title_collected_text):
    text_lower = details_collected_text.lower()
    title_lower = title_collected_text.lower()

    # Check if the lowercase text contains 'hali'
    essential_word = 'hali'
    if essential_word in text_lower or essential_word in title_lower:
        return True   
    else:
        return False   
    
# Initialize the OpenAI client with the API key
client = OpenAI(api_key=os.environ['CHATGPT_API'])


def is_description_heading_about_(description, heading):
    # Use the client to create a chat completion
    prompt = f"""
    Based on the following description and title for an item listed on Facebook Marketplace, determine if the item is a rug or floor runner. Respond strictly in the format 'yes|d1|d2' if it is a rug or floor runner, with 'd1' and 'd2' as the dimensions in meters. If the item is not a rug or floor runner, respond with 'no'. If dimensions cannot be determined, use 'na' for 'd1' and 'd2'.

    Description: {description}
    |||
    Title: {heading}

    Note: Your response should strictly follow the 'yes|d1|d2' or 'no' format without additional explanations.
    """
    completion = client.chat.completions.create(
        model="gpt-3.5-turbo",  # Ensure you're using the latest suitable model
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ]
    )

    if print_mode:
        print(f"Prompt: prompt")

    # Extract and process the answer
    answer = completion.choices[0].message.content.strip().lower()
    if print_mode:
        print(f"ChatGPT answer: {answer}")
    return answer

def check_dimensions(returned_string, desired_width=2.8, desired_height=2.3, tolerance=0.2):
    # Split the returned string
    parts = returned_string.split('|')
    
    # Ensure there are three parts and neither d1 nor d2 is 'na'
    if len(parts) == 3 and parts[1] != 'na' and parts[2] != 'na':
        try:
            # Convert d1 and d2 to float
            d1 = float(parts[1])
            d2 = float(parts[2])

            # Calculate the minimum and maximum dimensions with tolerance
            min_width = desired_width * (1 - tolerance)
            max_width = desired_width * (1 + tolerance)
            min_height = desired_height * (1 - tolerance)
            max_height = desired_height * (1 + tolerance)

            # Check if dimensions are within the desired range
            if min_width <= d1 <= max_width and min_height <= d2 <= max_height:
                return True
            else:
                return False
        except ValueError:
            # Handle the case where d1 or d2 cannot be converted to float
            return False
    else:
        return False


def visit_ids_with_playwright(item_ids):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)  # Set headless=True for headless mode
        page = browser.new_page()

        page.goto('https://www.facebook.com/marketplace/melbourne/search?daysSinceListed=1&query=grange')
        page.wait_for_timeout(3000)
        if screenshot_mode:
            page.screenshot(path=os.path.join(screenshot_path, 'visit_id_temp_page.png'))

        
        login_prompt = page.query_selector("text=/log in to continue/i")
        page.fill('input#email', os.environ['FB_EMAIL'])  # Using the ID selector for the email input field
        page.fill('input#pass', os.environ['FB_PASSWORD'])  # Using the ID selector for the password input field
        login_button = page.query_selector('button[name="login"]')
        login_button.click()
        page.wait_for_timeout(3000)
        if screenshot_mode:
            page.screenshot(path=os.path.join(screenshot_path, 'visit_id_clicked_login.png'))
            
        
        # initialise a log of visited ids
        visited_ids = set()
        # initialise a log of matched ids
        matched_ids = set()

        for item_id in item_ids:
            # Construct the URL for the item ID
            url = f"https://www.facebook.com/marketplace/item/{item_id}"
            
            # print attempting id
            print(f"Attempting to visit item ID: {item_id}")

            # Navigate to the URL
            page.goto(url)
            if screenshot_mode:
                page.screenshot(path=os.path.join(screenshot_path, 'visit_id_' + item_id + '.png'))
            
            # Selector for the button with aria-label="Close"
            close_button_selector = '[aria-label="Close"]'
            try:
                # Wait for the close button to become visible, with a timeout of 5 seconds
                page.wait_for_selector(close_button_selector, state='visible', timeout=5000)
                page.click(close_button_selector)
                print(f"Close button clicked for item ID: {item_id}")
            except TimeoutError:
                # If the close button doesn't appear within 5 seconds, this block is executed
                print("Close button not found within 5 seconds, continuing with the script.")
                
            # wait for safe
            page.wait_for_timeout(2000)
            
            see_more_button_xpath = '//text()[contains(., "...")]/following::span[contains(text(), "See more")][1]'

            see_more_button = page.query_selector(see_more_button_xpath)
            if see_more_button:
                # If the "See more" button exists, click it
                see_more_button.click()
            
            html_content = page.content()
            
            
            # Parse the HTML content with BeautifulSoup
            soup = BeautifulSoup(html_content, 'html.parser')
            
            ## capture the details ##
            # Initialize a flag to indicate whether we're currently between the start and end points
            details_collecting = False

            # List to hold all the text between "Details" and "Seller information"
            details_text_between = []
            
            # Check if "Seller information" is in the soup
            if soup.find(string=lambda text: "Seller information" in text):

                # Iterate through all text nodes in the document
                for text_node in soup.find_all(string=True):
                    # If we encounter "Seller information", stop collecting and don't include this text
                    if "Seller information" in text_node:
                        break  # Exit the loop before adding "Seller information" to text_between

                    if details_collecting:
                        details_text_between.append(text_node.strip())
                    
                    # Start collecting after encountering "Details"
                    if "Details" in text_node:
                        details_collecting = True

                # Join the collected text
                details_collected_text = ' '.join(details_text_between)
                

                # Initialize variables
                heading_collecting = False  # Don't start collecting text immediately
                collected_text_between = []  # List to hold all text collected between "Buy-and-sell groups" and "Listed"

                # Iterate through all text nodes in the document
                for text_node in soup.find_all(string=True):
                    # Start collecting when "Buy-and-sell groups" is found
                    if "Buy-and-sell groups" in text_node:
                        heading_collecting = True
                        continue  # Skip the text node that contains "Buy-and-sell groups"
                    
                    # Check if the current text node contains "Listed" and we are currently collecting
                    if "Listed" in text_node and heading_collecting:
                        break  # Stop collecting if "Listed" is found

                    if heading_collecting:
                        # Add the text to our list, stripping any leading/trailing whitespace
                        collected_text_between.append(text_node.strip())

                # Join the collected text
                heading_collected_text = ' '.join(collected_text_between)
                if print_mode:
                    print(f"This is the heading_collected_text: {heading_collected_text}")

                chat_gpt_response = ''
                
                # if exclude comes back false then it makes sense to use api credits to check if furniture
                if details_are_exclude(details_collected_text) == False and heading_details_keyword(details_collected_text, heading_collected_text) == True:
                    chat_gpt_response = is_description_heading_about_(details_collected_text, heading_collected_text)
                    if 'yes' in chat_gpt_response:
                        if check_dimensions(chat_gpt_response):
                            send_alert_email(item_id)
                            matched_ids.add(item_id + '|' + chat_gpt_response)
                        
            # add the visited id to the set
            visited_ids.add(item_id)

                


        # Close the browser after visiting all URLs
        browser.close()
        
        # return the visited ids and matched ids
        return visited_ids, matched_ids
        





if eid_csv_files:
    # Sort the files by their file name with the most recent first
    sorted_eid_csv_files = sorted(eid_csv_files, reverse=True)

    # The first file in the list now has the latest timestamp
    eid_latest_file = sorted_eid_csv_files[0]

    # Open and read the latest CSV file
    with open(eid_latest_file, 'r', encoding='utf-8') as eid_file:
        # Read IDs into a set
        eid_ids = set(eid_file.read().splitlines())
        print(f"Extracted ID: {eid_ids}")
        
    # Initialize vid_ids as an empty set in case there are no vid files
    vid_ids = set()
    matched_ids = set()

    if vid_csv_files:
        # Sort the files by their file name with the most recent first
        sorted_vid_csv_files = sorted(vid_csv_files, reverse=True)

        # The first file in the list now has the latest timestamp
        vid_latest_file = sorted_vid_csv_files[0]

        # Open and read the latest CSV file
        with open(vid_latest_file, 'r', encoding='utf-8') as vid_file:
            # Read IDs into a set
            vid_ids = set(vid_file.read().splitlines())
            
    if mid_csv_files:
        # Sort the files by their file name with the most recent first
        sorted_mid_csv_files = sorted(mid_csv_files, reverse=True)

        # The first file in the list now has the latest timestamp
        mid_latest_file = sorted_mid_csv_files[0]

        # Open and read the latest CSV file
        with open(mid_latest_file, 'r', encoding='utf-8') as mid_file:
            # Read IDs into a set
            matched_ids = set(mid_file.read().splitlines())
    

    # Filter out IDs from eid_ids that are present in vid_ids
    unique_eid_ids = eid_ids - vid_ids
    if unique_eid_ids:
        # order the ids
        unique_eid_ids = sorted(unique_eid_ids)
        returned_vid_ids, returned_mat_ids = visit_ids_with_playwright(unique_eid_ids)
        
        now = datetime.datetime.now(tz_aet)
        formatted_date = now.strftime("%Y-%m-%d-%H-%M-%S")
        
        # Save the visited ids to a CSV file if they exist
        if returned_vid_ids:
            new_vid_ids = vid_ids.union(returned_vid_ids)
            visited_file_name = os.path.join(visited_folder_path, f"{formatted_date}_visited_id.csv")
            with open(visited_file_name, 'a') as csvfile:
                for id in new_vid_ids:
                    csvfile.write(id + '\n')
                    
        # if there are matched ids write them to a csv file
        if returned_mat_ids:
            new_mid_ids = matched_ids.union(returned_mat_ids)
            matched_file_name = os.path.join(matched_folder_path, f"{formatted_date}_matched_id.csv")
            with open(matched_file_name, 'a') as csvfile:
                for id in new_mid_ids:
                    csvfile.write(id + '\n')
        
        


    
        
        
        
