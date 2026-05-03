# User Guide: Building Campaigns via Chat

Welcome to the GPMPE Chat Interface! This guide explains how to effectively communicate with the chatbot to build, modify, and manage your marketing campaigns.

## 1. Overview
The chatbot is designed to understand natural-language commands for modifying your business profile and campaign data. It is **context-aware**, meaning it remembers which campaign and component you are currently working on.

---

## 2. Managing Your Business Profile
You can update your business details using "set business" commands.

*   **Basic Details:**
    *   `set business display name to Solara Wellness`
    *   `set business legal name to Solara Wellness LLC`
    *   `set business timezone to America/Los_Angeles`
*   **Contact & Address:**
    *   `set business phone to 555-1212`
    *   `set business street address to 123 Market St`
    *   `set business city to Los Angeles`
    *   `set business zip code to 90001`

---

## 3. Managing Campaigns
Campaigns are the top-level containers for your promotions.

*   **Switching Campaigns:**
    *   Simply navigate to a campaign in the GUI, and the chatbot will automatically focus on it.
*   **Cloning Campaigns:**
    *   `clone summer-recharge and rename it to autumn-refresh`
    *   `clone summer-recharge renaming it to autumn-refresh for Solara`
*   **Global Campaign Fields:**
    *   `set the title to Autumn Refresh Specials`
    *   `set the objective to Increase weekday bookings in September`
    *   `set the start date to 2026-09-01`
    *   `set the footnote to Valid only at our Market St location.`
*   **Clearing Fields:**
    *   `delete the campaign footnote`
    *   `delete the campaign objective`

---

## 4. Managing Components
Components are the sections of your flyer (e.g., "Featured Offers", "Weekday Specials").

*   **Context Setting:**
    *   If you want to edit items in a specific section, tell the chatbot: `I am working on the featured-offers component.`
*   **Renaming Sections:**
    *   `rename the featured-offers component to community-appreciation`
    *   `change the display title of the weekday-specials component to Monthly Highlights`
*   **Changing Layouts:**
    *   `set component featured-offers type to weekday-specials` (This changes the visual style to a list format).
*   **Visual Tuning:**
    *   `set component featured-offers background color to lightgreen`
    *   `set component featured-offers accent header color to #ff0000`
    *   `delete the background color field for the weekday-specials component`

The business brand theme includes a **primary color**, which is the main brand color used by the renderer. Components that do not specify their own `background_color` fall back to the theme's primary color when that component style uses a primary-color panel. Use a component-specific background color when a section needs to stand apart; delete that field when you want the section to return to the primary brand color.

---

## 5. Managing Items
Items are the individual services or products within a component.

### 5.1 Adding Items
You can add items by name, clone existing ones, and specify their position.

*   **Simple Add:**
    *   `add a new item called Signature Facial`
*   **Add with Positioning:**
    *   `add a new item called Deep Tissue Massage after the Swedish Massage item`
    *   `add an item called Express Manicure before the first item`
*   **Cloning & Positioning:**
    *   `add a new item like the Signature Facial called Deluxe Facial before the last item`
    *   `create a new item like Swedish Massage called Lymphatic Drainage and add it between the Swedish Massage and Deep Tissue items`

### 5.2 Editing Items
You can refer to items by their **exact name** or their **ordinal position** (first, second, 3rd, last, etc.).

*   **By Name:**
    *   `set the price of the Signature Facial item to $99`
    *   `change the duration of the Swedish Massage item to 60 min`
*   **By Position:**
    *   `set the price of the first item to $45`
    *   `change the duration of the 2nd item in the weekday-specials component to 30 min`
*   **Bulk Edits:**
    *   `change the background color to white for all items in the featured-offers component`

### 5.3 Deleting Items
*   `delete the Signature Facial item`
*   `delete the last item in the weekday-specials component`

---

## 6. Tips for Success

1.  **Be Specific:** If you have multiple components, include the component name in your command (e.g., `set the price of the first item in the weekday-specials component to $50`).
2.  **Use Ordinals:** Commands like "first item", "second item", and "last item" are the most reliable way to target specific items.
3.  **Check the Preview:** The PDF preview on the left updates automatically after every successful command.
4.  **Error Messages:** If the chatbot doesn't understand, it will provide an example of a supported command to help you correct your phrasing.
