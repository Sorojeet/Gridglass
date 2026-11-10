"""Words for the pages search engines read: one page per tool, a few guides, and the site pages.

Kept as data so the templates stay small and every tool page has the same shape. Text may hold
simple HTML (<b>, <code>, <a>); it is written here, never taken from users.
"""
from __future__ import annotations

from dataclasses import dataclass, field

SITE_NAME = "Gridglass"
OPERATOR = "Mannu"
CITY = "Delhi"
CONTACT_EMAIL = "hello@gridglass.in"
UPDATED = "2 November 2026"  # privacy policy and terms

CATEGORIES = {
    "clean": "Clean",
    "shape": "Shape",
    "combine": "Combine",
    "summarize": "Summarize",
    "convert": "Convert",
}


@dataclass(frozen=True)
class Example:
    columns: list[str]
    before: list[list[str]]
    after: list[list[str]]
    after_columns: list[str] | None = None
    note: str = ""


@dataclass(frozen=True)
class ToolPage:
    slug: str
    op: str          # the tool in the app: /#/tool/<op>
    cat: str
    name: str        # as on the tool card
    title: str       # <title> and <h1>
    description: str
    intro: list[str]
    when: list[str]
    steps: list[str]
    example: Example | None
    options: list[tuple[str, str]]
    faqs: list[tuple[str, str]]
    related: list[str] = field(default_factory=list)  # slugs


TOOLS: list[ToolPage] = [
    # ------------------------------------------------------------------ clean
    ToolPage(
        slug="remove-duplicates", op="remove_duplicates", cat="clean", name="Remove duplicates",
        title="Remove duplicate rows from a CSV or spreadsheet",
        description="Find repeated rows in a CSV, XLSX or JSON file and remove them, list them, or mark them in a new "
                    "column. Choose which columns decide a duplicate. Free, works on phones.",
        intro=[
            "Duplicate rows creep in when lists are copied together, exported twice or typed by hand. "
            "They inflate totals and send the same email twice.",
            "This tool removes them in one step. A row can count as a duplicate when <b>every</b> cell "
            "matches, or only when chosen columns match, such as the same email address.",
            "Not sure yet? Choose <b>Show only them</b> to list every repeated row side by side, or <b>Mark them</b> "
            "to add a Duplicate column (Yes/No) and decide later.",
        ],
        when=[
            "A contact or customer list has the same person more than once.",
            "Two exports were pasted together and overlap.",
            "You want one row per order ID, keeping the most recent entry.",
        ],
        steps=[
            "Open the tool and choose your file (CSV, XLSX or JSON).",
            "Leave <b>All columns</b> on, or tap the columns that decide a duplicate, for example <i>Email</i>.",
            "Choose whether to keep the <b>first</b> or the <b>last</b> copy.",
            "Check the preview, which shows how many rows go, then download.",
        ],
        example=Example(
            columns=["Email", "Name", "City"],
            before=[["asha@example.com", "Asha", "Pune"], ["ravi@example.com", "Ravi", "Delhi"],
                    ["asha@example.com", "Asha R", "Pune"]],
            after=[["asha@example.com", "Asha", "Pune"], ["ravi@example.com", "Ravi", "Delhi"]],
            note="Duplicates decided by <i>Email</i>, keeping the first copy.",
        ),
        options=[
            ("A row is a duplicate when", "All columns match, or only the columns you choose."),
            ("What to do with them", "Remove them, show only them (every copy, side by side), or mark them in a new column."),
            ("Which copy is the original", "The first one in the file, or the last one. The others are removed or marked."),
        ],
        faqs=[
            ("Does it notice ‘Asha’ and ‘asha ’ as the same?",
             "Not on its own, because they are different text. Run <a href=\"/tools/trim-spaces\">Trim spaces</a> "
             "and <a href=\"/tools/change-case\">Change case</a> first, then remove duplicates."),
            ("Can I see the duplicates before they are removed?",
             "Yes. Choose <b>Show only them</b> to list every repeated row, or <b>Mark them</b> to add a Yes/No column. "
             "The live preview also shows how many rows would go before you download anything."),
            ("Is the order of my rows kept?", "Yes. Rows stay in their original order."),
        ],
        related=["trim-spaces", "change-case", "filter-rows", "sort-rows"],
    ),
    ToolPage(
        slug="trim-spaces", op="trim", cat="clean", name="Trim spaces",
        title="Trim extra spaces from text in a CSV or spreadsheet",
        description="Remove spaces before and after text, and turn double spaces into one, across whole columns "
                    "of a CSV or XLSX file. Fixes matching and lookups that fail for no visible reason.",
        intro=[
            "A space you can't see at the end of ‘Pune ’ makes it different from ‘Pune’. Filters miss it, "
            "lookups fail and duplicates survive.",
            "Trim spaces cleans every text cell in the columns you pick: spaces at the start and end go, and "
            "runs of spaces inside the text can become a single space.",
        ],
        when=[
            "A filter for a city or name misses rows that look identical.",
            "Data was copied from a web page, PDF or another system.",
            "Before removing duplicates or matching two files.",
        ],
        steps=[
            "Open the tool and choose your file.",
            "Keep <b>All text columns</b> or pick the columns to clean.",
            "Leave <b>double spaces into one</b> on unless you need them.",
            "Check the preview and download, or carry on with another tool.",
        ],
        example=Example(
            columns=["Name", "City"],
            before=[["␣␣Asha Rao␣", "Pune␣"], ["Ravi␣␣Kumar", "␣Delhi"]],
            after=[["Asha Rao", "Pune"], ["Ravi Kumar", "Delhi"]],
            note="␣ marks a space.",
        ),
        options=[
            ("Columns", "All text columns, or the ones you choose. Numbers and dates are left alone."),
            ("Double spaces into one", "Also collapses repeated spaces inside the text."),
        ],
        faqs=[
            ("Will it change my numbers?", "No. Only text columns are trimmed."),
            ("What about spaces between words?",
             "Single spaces between words stay. With the option on, two or more spaces become one."),
            ("Can I undo it?", "Yes. Every step can be edited or removed from the result screen before you download."),
        ],
        related=["remove-duplicates", "change-case", "replace-values", "merge-files"],
    ),
    ToolPage(
        slug="change-case", op="change_case", cat="clean", name="Change case",
        title="Change text to UPPER, lower or Title Case online",
        description="Make names, cities and codes consistent: convert whole columns of a CSV or spreadsheet to "
                    "UPPER CASE, lower case or Title Case in one step.",
        intro=[
            "Lists typed by different people mix ‘PUNE’, ‘pune’ and ‘Pune’. To a computer those are three "
            "different cities, so totals split and duplicates hide.",
            "Change case rewrites the text in the columns you choose so it all follows one style.",
        ],
        when=[
            "Names arrive in capitals from one system and lower case from another.",
            "You want email addresses in lower case before matching them.",
            "Product codes must be in capitals.",
        ],
        steps=[
            "Open the tool and choose your file.",
            "Tap the text columns to change.",
            "Pick <b>UPPER</b>, <b>lower</b> or <b>Title</b>.",
            "Check the preview and download.",
        ],
        example=Example(
            columns=["Name", "Email"],
            before=[["meera iyer", "Meera@Example.com"], ["DEV SINGH", "DEV@EXAMPLE.COM"]],
            after=[["Meera Iyer", "meera@example.com"], ["Dev Singh", "dev@example.com"]],
            note="Name changed to Title, Email to lower, as two steps.",
        ),
        options=[("Columns", "The text columns to change."), ("Change to", "UPPER, lower or Title (Each Word Capitalised).")],
        faqs=[
            ("Can I use different styles for different columns?",
             "Yes. Run the tool once per style; each run becomes a step you can edit later."),
            ("Does Title case handle names like ‘McDonald’?",
             "It capitalises the first letter of each word, so ‘mcdonald’ becomes ‘Mcdonald’. Fix special cases "
             "with <a href=\"/tools/replace-values\">Replace values</a>."),
        ],
        related=["trim-spaces", "remove-duplicates", "replace-values"],
    ),
    ToolPage(
        slug="replace-values", op="replace_values", cat="clean", name="Replace values",
        title="Find and replace values, and clean up text in a spreadsheet",
        description="Find and replace text in chosen columns, or clean it up: remove special characters, keep only "
                    "digits or letters, or pull out an email's domain or the first word.",
        intro=[
            "Placeholder values such as ‘N/A’, ‘-’ or ‘unknown’ get in the way of totals and filters, and "
            "spelling differences split one thing into two.",
            "Replace values swaps one value for another in the columns you pick. It can match the whole cell "
            "or any part of the text, and an empty replacement clears the cell.",
            "Its <b>Clean up text</b> option fixes common messes in one go: remove special characters such as ₹ , . - !, "
            "keep only the digits of a phone number, keep only letters, turn an email address into its domain, or keep "
            "just the first or last word. Hindi and other Indian scripts are kept intact.",
        ],
        when=[
            "Clearing ‘N/A’ or ‘-’ so a column becomes numbers.",
            "Fixing a spelling everywhere, such as ‘Bangalore’ to ‘Bengaluru’.",
            "Removing a prefix such as ‘ID-’ from codes.",
            "Keeping only the digits of phone numbers like ‘+91 98765-43210’.",
        ],
        steps=[
            "Open the tool and choose your file.",
            "Tap the columns to search.",
            "Type what to <b>find</b> and what to <b>replace it with</b> (leave empty to clear).",
            "Choose <b>whole cell</b> or <b>part of the text</b>, then check the preview.",
        ],
        example=Example(
            columns=["City", "Amount"],
            before=[["Bangalore", "1200"], ["Pune", "N/A"]],
            after=[["Bengaluru", "1200"], ["Pune", ""]],
            note="Two replacements: a spelling fix and clearing ‘N/A’.",
        ),
        options=[
            ("Match", "Whole cell, or part of the text anywhere in the cell."),
            ("Match capital letters exactly", "Off by default, so ‘n/a’ and ‘N/A’ are both found."),
            ("Clean up text", "Remove special characters, keep only digits, keep only letters, email → domain, "
                              "keep the first word, or keep the last word."),
        ],
        faqs=[
            ("Can I replace several different values?", "Yes. Add one Replace values step per value."),
            ("Does it work on numbers?",
             "Yes, for whole-cell matches. To change all numbers by a rule, use <a href=\"/tools/add-column\">Add column</a> with math."),
        ],
        related=["trim-spaces", "fill-blanks", "change-type"],
    ),
    ToolPage(
        slug="fill-blanks", op="fill_blanks", cat="clean", name="Fill blanks",
        title="Fill empty cells or fill down in a CSV or spreadsheet",
        description="Fill blank cells with a value such as 0 or ‘Unknown’, or copy the value from the row above "
                    "(fill down) or below. Works on whole columns at once.",
        intro=[
            "Reports often show a group name once and leave the rows under it empty. Sorting or filtering then "
            "loses which group a row belongs to.",
            "Fill blanks puts something in every empty cell: a value you type, the value from the row above "
            "(fill down) or the value from the row below.",
        ],
        when=[
            "A report lists a region once, with blank cells under it.",
            "Empty amounts should count as 0.",
            "Missing categories should read ‘Unknown’.",
        ],
        steps=[
            "Open the tool and choose your file.",
            "Keep <b>All columns</b> or choose the columns to fill.",
            "Pick <b>A value</b>, <b>Row above</b> or <b>Row below</b>.",
            "Check the preview and download.",
        ],
        example=Example(
            columns=["Region", "Shop", "Sales"],
            before=[["North", "Karol Bagh", "120"], ["", "Rohini", "95"], ["South", "Adyar", ""]],
            after=[["North", "Karol Bagh", "120"], ["North", "Rohini", "95"], ["South", "Adyar", "0"]],
            note="Region filled down; Sales filled with 0.",
        ),
        options=[("Fill with", "A value, the row above, or the row below."), ("Columns", "All columns or the ones you choose.")],
        faqs=[
            ("Does ‘Row above’ work if several cells in a row are empty?",
             "Yes. Each empty cell takes the nearest filled value above it."),
            ("Will a typed value change the column's type?",
             "Gridglass converts the value to the column's type, so ‘0’ fills a number column as the number 0."),
        ],
        related=["remove-blank-rows", "replace-values", "pivot-table"],
    ),
    ToolPage(
        slug="remove-blank-rows", op="remove_blank_rows", cat="clean", name="Remove blank rows",
        title="Remove blank or incomplete rows from a CSV or spreadsheet",
        description="Delete rows where every cell is empty, or rows missing a value in columns that matter, "
                    "such as an email or amount.",
        intro=[
            "Exports and hand-made sheets collect empty rows, and half-filled rows that shouldn't be counted.",
            "This tool removes rows that are completely blank, or rows with any blank cell in the columns you choose.",
        ],
        when=[
            "A sheet has empty lines between blocks of data.",
            "Rows without an email address are useless for a mailing.",
            "Totals should only include rows with an amount.",
        ],
        steps=[
            "Open the tool and choose your file.",
            "Choose <b>Every cell is blank</b> or <b>Any cell is blank</b>.",
            "Optionally choose which columns to look at.",
            "Check the preview and download.",
        ],
        example=Example(
            columns=["Name", "Email"],
            before=[["Asha", "asha@example.com"], ["", ""], ["Ravi", ""]],
            after=[["Asha", "asha@example.com"]],
            note="‘Any cell is blank’, looking at Name and Email.",
        ),
        options=[("Remove a row when", "Every cell is blank, or any cell is blank."), ("Look at", "All columns or the ones you choose.")],
        faqs=[
            ("Does a cell with only spaces count as blank?",
             "Yes. Empty cells and cells with only spaces both count as blank."),
        ],
        related=["fill-blanks", "filter-rows", "trim-spaces"],
    ),
    # ------------------------------------------------------------------ shape
    ToolPage(
        slug="filter-rows", op="filter_rows", cat="shape", name="Filter rows",
        title="Filter rows in a CSV or spreadsheet online",
        description="Keep only the rows you need: by text, numbers, dates or blanks, with up to 20 conditions "
                    "matched all together or any one. Pick values from a list of what's in the column.",
        intro=[
            "Filter rows keeps the rows that match your conditions and leaves the rest out of the result. "
            "Your original file is never changed.",
            "Conditions can compare text (is, contains, starts with), numbers and dates (more than, at most), "
            "check for blanks, or match a list of values. While you type, Gridglass suggests values that "
            "actually appear in the column, with how often each appears.",
        ],
        when=[
            "Orders from one city, or several cities.",
            "Amounts over a certain value, or dates after a day.",
            "Rows where an important column is empty, to fix them.",
        ],
        steps=[
            "Open the tool and choose your file.",
            "Pick a column, a condition and a value (or choose from the list).",
            "Add more conditions and choose <b>all</b> or <b>any</b> must match.",
            "Check the preview and the row count, then download.",
        ],
        example=Example(
            columns=["City", "Amount"],
            before=[["Pune", "450"], ["Delhi", "1200"], ["Pune", "1800"]],
            after=[["Pune", "1800"]],
            note="City is Pune <b>and</b> Amount is more than 1000.",
        ),
        options=[
            ("Conditions", "is, is not, contains, doesn't contain, starts with, ends with, is more than, is at least, "
                           "is less than, is at most, is blank, is not blank, is one of."),
            ("Rows must match", "All conditions or any condition."),
        ],
        faqs=[
            ("Are text matches case-sensitive?", "No. ‘pune’ finds ‘Pune’."),
            ("Can I filter dates?", "Yes. Date columns compare as dates, so ‘is more than 2026-03-31’ means after 31 March."),
            ("Can I make one file per city instead?", "Yes. Use <a href=\"/tools/split-into-pages\">Split into pages</a>."),
        ],
        related=["sort-rows", "keep-top-rows", "pivot-table", "split-into-pages"],
    ),
    ToolPage(
        slug="sort-rows", op="sort_rows", cat="shape", name="Sort rows",
        title="Sort a CSV or spreadsheet by one or more columns",
        description="Sort rows A to Z, Z to A, smallest or largest first, by one column and then by others to "
                    "break ties. Numbers and dates sort correctly, not as text.",
        intro=[
            "Sort rows puts your rows in order by one column, then by a second column for rows that tie, and so on.",
            "Because Gridglass knows each column's type, numbers sort as numbers (2 before 10) and dates sort by date.",
        ],
        when=["Largest orders first.", "Customers A to Z within each city.", "Newest dates at the top."],
        steps=[
            "Open the tool and choose your file.",
            "Pick the column to sort by and the direction.",
            "Tap <b>Then by</b> to add a tie-breaker.",
            "Check the preview and download.",
        ],
        example=Example(
            columns=["City", "Amount"],
            before=[["Pune", "450"], ["Delhi", "1200"], ["Pune", "1800"]],
            after=[["Delhi", "1200"], ["Pune", "1800"], ["Pune", "450"]],
            note="City A→Z, then Amount largest first.",
        ),
        options=[("Sort by", "Any column, A→Z / smallest first or Z→A / largest first, with up to 10 tie-breakers.")],
        faqs=[
            ("Where do blank cells go?", "Blank cells go last, whichever direction you sort."),
            ("How do I get the top 10?",
             "Sort largest first, then use <a href=\"/tools/keep-top-rows\">Keep top or bottom rows</a>."),
        ],
        related=["keep-top-rows", "filter-rows", "remove-duplicates"],
    ),
    ToolPage(
        slug="remove-columns", op="remove_columns", cat="shape", name="Remove columns",
        title="Remove columns from a CSV or spreadsheet",
        description="Delete the columns you don't need from a CSV, XLSX or JSON file by tapping them. "
                    "Smaller files, clearer reports.",
        intro=[
            "Exports often carry dozens of columns you never use. Removing them makes the file easier to read, "
            "smaller to send and quicker to work with.",
        ],
        when=["Removing internal IDs before sharing a file.", "Dropping personal data you don't need.", "Cutting a wide export down to size."],
        steps=["Open the tool and choose your file.", "Tap each column to remove.", "Check the preview and download."],
        example=Example(
            columns=["ID", "Name", "Phone", "City"],
            before=[["A17", "Asha", "98•••", "Pune"]],
            after_columns=["Name", "City"],
            after=[["Asha", "Pune"]],
        ),
        options=[("Columns to remove", "Tap any number of columns. Select all and Clear are there for long lists.")],
        faqs=[("Can I also reorder columns?", "Yes. Use <a href=\"/tools/choose-columns\">Choose &amp; reorder columns</a> instead.")],
        related=["choose-columns", "rename-columns", "convert-file"],
    ),
    ToolPage(
        slug="choose-columns", op="keep_columns", cat="shape", name="Choose & reorder columns",
        title="Choose and reorder columns in a CSV or spreadsheet",
        description="Keep only the columns you want, in the order you tap them. Everything else is left out.",
        intro=[
            "When a file has many columns and you need a few, it's quicker to say which to keep. The order you "
            "tap them in becomes the order in the result.",
        ],
        when=["Preparing a file for an upload that needs columns in a set order.", "Making a short report from a long export."],
        steps=["Open the tool and choose your file.", "Tap the columns to keep, in the order you want.", "Check the preview and download."],
        example=Example(
            columns=["ID", "City", "Name", "Amount"],
            before=[["A17", "Pune", "Asha", "450"]],
            after_columns=["Name", "Amount", "City"],
            after=[["Asha", "450", "Pune"]],
        ),
        options=[("Columns, in order", "Numbers on each chip show the new order.")],
        faqs=[("What happens to columns I don't tap?", "They are left out of the result. Your original file is never changed.")],
        related=["remove-columns", "rename-columns"],
    ),
    ToolPage(
        slug="rename-columns", op="rename_columns", cat="shape", name="Rename columns",
        title="Rename column headers in a CSV or spreadsheet",
        description="Give columns clear names: type a new name next to any header. Useful before sharing files "
                    "or matching another file's headers.",
        intro=[
            "System exports use headers like ‘cust_nm_1’. Renaming them makes a file readable, and matching "
            "names make <a href=\"/tools/stack-files\">stacking</a> and <a href=\"/tools/merge-files\">merging</a> easier.",
        ],
        when=["Cleaning up codes into plain names.", "Making two files use the same headers."],
        steps=["Open the tool and choose your file.", "Type new names next to the columns to rename.", "Check the preview and download."],
        example=Example(columns=["cust_nm", "amt"], before=[["Asha", "450"]], after_columns=["Customer", "Amount"], after=[["Asha", "450"]]),
        options=[("New names", "Leave a box empty to keep the current name. Names must be unique.")],
        faqs=[("Headers are on the wrong row. What can I do?",
               "Tap <b>Headers</b> on the file card in the app to choose the row that holds the column names.")],
        related=["choose-columns", "stack-files", "merge-files"],
    ),
    ToolPage(
        slug="keep-top-rows", op="keep_rows", cat="shape", name="Keep top or bottom rows",
        title="Keep the top or bottom rows of a CSV or spreadsheet",
        description="Keep only the first or last N rows. Sort first to get a top 10 or bottom 5 by any column.",
        intro=["Keep top or bottom rows cuts a file down to its first or last rows. Combined with sorting it gives "
               "you a top-10 list in two steps."],
        when=["Top 10 customers by sales.", "The last 50 transactions.", "A small sample of a huge file to share."],
        steps=["Sort the file first if order matters.", "Choose <b>First rows</b> or <b>Last rows</b>.", "Type how many, then download."],
        example=Example(columns=["Customer", "Sales"], before=[["Asha", "1800"], ["Ravi", "1200"], ["Meera", "450"]],
                        after=[["Asha", "1800"], ["Ravi", "1200"]], note="Sorted largest first, then the first 2 rows."),
        options=[("Keep", "First rows or last rows."), ("How many", "Any number from 1.")],
        faqs=[("Does it sort for me?", "No; it keeps rows in their current order. Add a <a href=\"/tools/sort-rows\">Sort rows</a> step first.")],
        related=["sort-rows", "filter-rows", "pivot-table"],
    ),
    ToolPage(
        slug="change-type", op="change_type", cat="shape", name="Change type",
        title="Change column types: text, numbers and dates",
        description="Turn text into numbers or dates, or numbers into text, so sorting, filtering and totals "
                    "work. Supports custom date formats like 31/12/2026.",
        intro=[
            "Gridglass already reads most columns correctly, including amounts like ‘₹1,23,456.50’ and dates "
            "like ‘5 Mar 2026’. When a column still needs a different type, Change type converts it.",
            "Cells that can't be converted become blank, and the preview shows you before you download.",
        ],
        when=["A code column with numbers should stay text, such as PIN codes.", "Dates in an unusual format need reading as dates."],
        steps=["Open the tool and choose your file.", "Pick a column and the new type; add more columns if needed.",
               "For unusual dates, enter a format such as <code>%d/%m/%Y</code>.", "Check the preview and download."],
        example=None,
        options=[("Types", "Text, whole number, decimal number, true/false, date, date &amp; time."),
                 ("Date format", "Optional, for example <code>%d/%m/%Y</code> for 31/12/2026 or <code>%m-%d-%Y</code>.")],
        faqs=[("Why do long numbers stay as text?",
               "Whole numbers longer than 10 digits, and numbers starting with 0, stay text on purpose so IDs, phone and card "
               "numbers keep every digit. Spreadsheet apps keep only 15 significant digits.")],
        related=["replace-values", "split-column", "filter-rows"],
    ),
    ToolPage(
        slug="split-column", op="split_column", cat="shape", name="Split column",
        title="Split one column into several by a separator",
        description="Break text like ‘Asha Rao’ into First and Last name, or ‘Pune, Maharashtra’ into city and "
                    "state, at a comma, space, dash or any separator.",
        intro=["Split column cuts the text in one column at each separator and puts the pieces into new columns."],
        when=["Full names into first and last name.", "‘City, State’ into two columns.", "Codes like ‘IN-DL-2026’ into parts."],
        steps=["Open the tool and choose your file.", "Pick the column and the separator.", "Choose how many columns to make.",
               "Check the preview and download."],
        example=Example(columns=["Name"], before=[["Asha Rao"], ["Ravi Kumar"]], after_columns=["Name 1", "Name 2"],
                        after=[["Asha", "Rao"], ["Ravi", "Kumar"]]),
        options=[("Split at each", "Comma, space, semicolon, dash, slash, bar or any text you type."),
                 ("Into how many columns", "2 to 50. Extra pieces stay together in the last column."),
                 ("Keep the original column", "Off by default.")],
        faqs=[("What if some rows have fewer parts?", "The extra columns are blank for those rows.")],
        related=["add-column", "rename-columns", "trim-spaces"],
    ),
    ToolPage(
        slug="add-column", op="add_column", cat="shape", name="Add column",
        title="Add a column: if-then rules, part of a text, date parts, ranges, totals and more",
        description="Make a new column with if-then rules, part of a text (first or last characters, text before or "
                    "after a symbol), the month or financial year of a date, number ranges, joined columns, simple math, "
                    "a running total, a rank or a % of total.",
        intro=["Add column creates a new column from what's already there, with no formulas to write.",
               "<b>If … then …</b> rules label rows by any condition (‘if Amount is at least 500, then Big’), checked in "
               "order. <b>Part of a date</b> pulls out the month, quarter, weekday or Indian financial year (FY 2025-26). "
               "<b>Number ranges</b> groups numbers into bands such as ‘Under 100’ and ‘100 – under 500’.",
               "<b>Part of a text</b> takes a piece of a text column: the first or last few characters, characters "
               "from the middle, the text before, after or between symbols (the domain after @ in an email, the city "
               "inside brackets), a word, the length, where something appears, or a code padded with zeros (7 → 00007).",
               "Running total, rank and % of total can count over the whole file or restart for each group, so "
               "‘rank within each city’ or ‘% of each region's sales’ is one step."],
        when=["Full name from first and last name.", "Total = Price × Quantity.", "A Country column that says ‘India’ on every row.",
              "Rank salespeople by sales, within each branch.", "Each product's share of total sales, as a %.",
              "Label orders High, Medium or Low by amount.", "A Financial year column for April–March reports.",
              "Age bands like 18–25, 25–40 and 40+.", "The year from an invoice number like INV-2026-001.",
              "Email domains, surnames, or the city inside brackets.", "Employee codes padded to 00042."],
        steps=["Open the tool and choose your file.", "Name the new column.", "Choose <b>Join columns</b>, <b>Math</b> or <b>One value</b>.",
               "Check the preview and download."],
        example=Example(columns=["Price", "Qty"], before=[["250", "2"], ["99.5", "4"]], after_columns=["Price", "Qty", "Total"],
                        after=[["250", "2", "500"], ["99.5", "4", "398"]], note="Math: Price × Qty."),
        options=[("Join columns", "Pick columns in order and what goes between them."),
                 ("Math", "+, −, × or ÷ with a number or another column."),
                 ("One value", "The same text or number on every row."),
                 ("If … then …", "Up to 20 rules using the same conditions as Filter rows; the first that matches wins, "
                                  "with an ‘Otherwise’ value. If every answer is a number, the column is a number column."),
                 ("Part of a date", "Month name or number, year, year-month, quarter, financial year (April–March), weekday, "
                                    "day of the month or week of the year."),
                 ("Part of a text", "Before, after or between (the first or last time it appears; blank or the "
                                    "whole text when it isn't there; optionally ignoring capitals), first, last or "
                                    "middle characters, a word counted from the start or end, length, position, or "
                                    "pad to a length. Numbers and dates are read as they're shown. The result is "
                                    "text; length and position are numbers."),
                 ("Number ranges", "Type where ranges start, such as 100, 500, 1000. A number on a boundary goes in the higher "
                                   "range. Optionally give each range a name."),
                 ("Running total", "Adds up a number column row by row, in the current order. Sort first if order matters."),
                 ("Rank", "1 for the largest (or smallest); equal values share a rank, like 1, 2, 2, 4."),
                 ("% of total", "Each row's share of the column total, rounded to 2 decimals."),
                 ("Count over", "The whole file, or each group separately (choose the grouping columns).")],
        faqs=[("What happens when dividing by zero?", "The result is blank for that row."),
              ("What about blank numbers?", "A running total treats them as 0; rank, % and ranges leave them blank."),
              ("Are these like LEFT, RIGHT, MID, TEXTBEFORE and TEXTAFTER?", "Yes. First characters is like LEFT, "
               "Last characters like RIGHT, Characters from the middle like MID, and Text before / after like "
               "TEXTBEFORE and TEXTAFTER. Length is LEN and Position is FIND, with no formulas to write."),
              ("Can it get the number out of a code like INV-2026-001?", "Use Text after ‘-’ with ‘Last’ for 001, "
               "or Characters from the middle (start at 5, 4 characters) for 2026. Then use "
               "<a href=\"/tools/change-type\">Change type</a> if you need it as a number."),
              ("My dates aren't offered for ‘Part of a date’.", "The column is probably text. Use "
               "<a href=\"/tools/change-type\">Change type</a> to make it a date first.")],
        related=["split-column", "pivot-table", "rename-columns"],
    ),
    # ------------------------------------------------------------------ combine
    ToolPage(
        slug="merge-files", op="merge", cat="combine", name="Merge files (lookup)",
        title="Look up values from a second file and merge two spreadsheets",
        description="Bring columns from a second CSV or spreadsheet by matching a column in both, such as Order ID "
                    "or Email. Every kind of join: lookup, matches only, all rows, no match.",
        intro=[
            "Merge files works like a lookup. For each row in your file, Gridglass finds the matching row in a "
            "second file and brings over the columns you choose.",
            "It can also combine two files in other ways: only rows found in both, every row from both, or only "
            "rows with no match, which is handy for finding what's missing.",
        ],
        when=["Add each customer's region from a separate list.", "Find orders that have no payment yet.",
              "Combine two exports that share an ID."],
        steps=["Open the tool and choose your main file.", "Add the second file.",
               "Choose the matching columns (Gridglass suggests columns with the same name).",
               "Pick what to keep and which columns to bring in, then check the preview."],
        example=Example(columns=["Order", "City"], before=[["1001", "Pune"], ["1002", "Delhi"]],
                        after_columns=["Order", "City", "Region"], after=[["1001", "Pune", "West"], ["1002", "Delhi", "North"]],
                        note="Second file: City → Region."),
        options=[("Match rows where", "Up to 5 column pairs."),
                 ("Keep", "All rows here + matches (lookup), only matches, all rows from both, all rows from the second file, "
                          "only rows with no match, or only rows that have a match."),
                 ("If a match appears more than once", "Use the first one (on by default), so your rows aren't repeated.")],
        faqs=[("The match column is numbers in one file and text in the other. Does it still work?",
               "Yes. The second file's key is converted to your file's type."),
              ("The second file has a title above its table.",
               "Gridglass usually finds the real header row on its own. If not, tap <b>Headers</b> on the second file's "
               "card and pick the row with the column names."),
              ("How is this different from Stack files?",
               "Merge adds <i>columns</i> side by side by matching rows. <a href=\"/tools/stack-files\">Stack files</a> "
               "puts <i>rows</i> underneath.")],
        related=["stack-files", "trim-spaces", "remove-duplicates"],
    ),
    ToolPage(
        slug="stack-files", op="stack", cat="combine", name="Stack files",
        title="Combine CSV and spreadsheet files into one (append rows)",
        description="Put the rows of several files one under another, such as twelve monthly reports into one. "
                    "Columns are matched by name, in any order, with an optional column for the file name.",
        intro=[
            "Stack files appends files: the rows of each added file go under the rows of the first.",
            "Columns are matched by name, ignoring capitals and extra spaces, so ‘Amount’ and ‘amount ’ line up even "
            "if the columns are in a different order. A column that only some files have is left blank for the others.",
        ],
        when=["Monthly or branch-wise reports into one table.", "Exports split into parts because of size limits.",
              "Lists collected from different people with the same headings."],
        steps=["Open the tool and choose the first file.", "Add the other files; you can choose several at once.",
               "Optionally add a column saying which file each row came from.", "Check the preview and download."],
        example=Example(columns=["Order", "Amount"], before=[["1001", "450"], ["1002", "1200"]],
                        after_columns=["Order", "Amount", "Source file"],
                        after=[["1001", "450", "jan.csv"], ["1002", "1200", "jan.csv"], ["2001", "980", "feb.csv"]],
                        note="feb.csv added underneath, with the source column on."),
        options=[("Files to add", "Up to 50 files."),
                 ("Add a column saying which file each row came from", "With a name of your choice; it goes last.")],
        faqs=[("What if a column has numbers in one file and text in another?",
               "It becomes text, so no values are lost."),
              ("Can I remove duplicates afterwards?", "Yes. <a href=\"/tools/remove-duplicates\">Remove duplicates</a> "
               "is suggested as the next step.")],
        related=["remove-duplicates", "merge-files", "pivot-table"],
    ),
    # ------------------------------------------------------------------ summarize
    ToolPage(
        slug="pivot-table", op="pivot", cat="summarize", name="Pivot table",
        title="Make a pivot table online: group, total and chart",
        description="Summarise data by group: totals, averages, counts and more, with optional columns across the top "
                    "and grand totals. Turn the result into a column, bar, line or pie chart.",
        intro=[
            "A pivot table answers questions like ‘total sales per city’ or ‘orders per month per product’. Choose "
            "the <b>Rows</b> to group by, the <b>Values</b> to calculate and, optionally, a <b>Columns</b> field to "
            "spread the totals across the top.",
            "Without a Columns field it works as a simple group-by. The Chart tab draws the result, and charts "
            "download as PNG or SVG.",
        ],
        when=["Sales per region and month.", "How many orders each customer placed.", "Average order value per city.",
              "Top customers first, sorted by their total.", "A separate sheet for each region or salesperson."],
        steps=["Open the tool and choose your file.", "Pick Rows, then add Values (sum, average, count…).",
               "Optionally pick a Columns field and grand totals.", "Switch to Chart to visualise it, then download."],
        example=Example(columns=["City", "Amount"], before=[["Pune", "450"], ["Delhi", "1200"], ["Pune", "1800"]],
                        after_columns=["City", "Sum of Amount"], after=[["Delhi", "1200"], ["Pune", "2250"], ["Grand total", "3450"]]),
        options=[("Calculations", "Sum, average, count rows, count values, count unique, smallest, largest, median, first, last."),
                 ("Grand totals", "A total row and, with a Columns field, a total column."),
                 ("Sort", "As in the file, by the Rows (A → Z or Z → A), or by any value, largest or smallest first. "
                          "With a Columns field, rows sort by their total. The Grand Total row stays at the bottom."),
                 ("One sheet for each (report filter pages)", "Pick a column such as Region: you get one pivot for each "
                  "region, each with its own Grand Total. Download as XLSX for one sheet per region, PDF for one "
                  "section each, or CSV/JSON for one file each in a .zip. Up to 200 pages."),
                 ("Only count rows where", "Optional filters (the same conditions as Filter rows) applied before grouping, "
                                           "so totals and the Grand Total only count matching rows."),
                 ("Chart", "Column, bar, line or pie; follows light and dark mode.")],
        faqs=[("How many columns can the Columns field make?", "Up to 200."),
              ("Is there something like Show Report Filter Pages?", "Yes: choose a column under <b>One sheet for "
               "each</b>. Each value gets its own pivot and, in the .xlsx download, its own sheet named after it. "
               "Turn it off on the download screen to get everything in one table."),
              ("Can I sort a pivot table by the totals?", "Yes. Under <b>Sort</b>, pick a value such as ‘Sum of "
               "Amount, largest first’."),
              ("Can I edit the pivot after making it?", "Yes. Tap Edit on the result screen; the preview updates live."),
              ("How are decimals shown?", "Sums, averages and medians are rounded to two decimal places, and decimals "
               "are shown with exactly two (1250.50) in the preview and in CSV, XLSX and PDF downloads. Counts stay "
               "whole numbers.")],
        related=["make-a-chart", "filter-rows", "transpose", "sort-rows"],
    ),
    ToolPage(
        slug="make-a-chart", op="chart", cat="summarize", name="Make a chart",
        title="Make a chart from a CSV or spreadsheet",
        description="Turn a CSV or XLSX file into a column, bar, line, area, pie or donut chart in a few taps. Add titles, "
                    "pick colours, show values, sort, keep the top 10, then download PNG or SVG.",
        intro=[
            "Make a chart groups your data and draws it straight away: choose what to group by (such as City) and what to "
            "add up (such as Sum of Amount). It uses the same engine as the <a href=\"/tools/pivot-table\">Pivot table</a>, "
            "opened on its Chart tab, so you can switch to the table at any time.",
            "Under <b>Customise the chart</b> you can add a title and axis titles, choose a colour set, show the values on "
            "the chart, sort largest first, keep only the top 5, 10 or 20 (the rest become ‘Other’), stack the series, "
            "choose short (1.2L) or full numbers, and pick a wide, square or tall shape.",
        ],
        when=["Sales by city for a presentation or WhatsApp group.", "Monthly totals as a line or area chart.",
              "Each product's share as a pie or donut.", "Top 10 customers as a bar chart."],
        steps=["Open the tool and choose your file.", "Pick the Rows to group by and the value to calculate.",
               "Choose the chart type, then open <b>Customise the chart</b> to style it.",
               "Download it as PNG (for messages and slides) or SVG (sharp at any size)."],
        example=None,
        options=[
            ("Chart types", "Column, bar, line, area, pie and donut. Add a Columns field for several series, then stack them."),
            ("Titles", "A chart title and titles for both axes."),
            ("Colours", "Gridglass (follows light and dark mode), Ocean, Sunset, Forest, Berry or Grey."),
            ("Order and size", "As in the table, largest first, smallest first or A → Z; all, top 5, top 10 or top 20."),
            ("Labels", "Data labels can show any mix of the name (on pies and donuts), the value and the percentage "
                       "(on pies, each slice's share; on other charts, each bar's share of its series, or of its stack when "
                       "stacked). The legend and grid lines can be turned on or off."),
            ("Filter", "‘Only count rows where’ limits the chart to some rows, such as City is Pune, before anything is added up."),
            ("Numbers", "Short (1.2L, 3.4Cr) or full (1,23,456)."),
            ("Shape", "Wide (720 × 400), square (560 × 560) or tall (480 × 640). PNG downloads are twice that size."),
        ],
        faqs=[("How many bars can a chart show?", "Up to 30 categories. Use Show: Top 10 to group the rest as ‘Other’."),
              ("Does the downloaded chart match what I see?", "Yes. The same drawing is saved, with a solid background."),
              ("Can I chart a column that is text?", "Charts add up numbers. Count rows instead (the default), or use "
               "<a href=\"/tools/change-type\">Change type</a> to turn the text into numbers.")],
        related=["pivot-table", "filter-rows", "sort-rows", "convert-file"],
    ),
    ToolPage(
        slug="transpose", op="unpivot", cat="summarize", name="Transpose or unpivot",
        title="Transpose rows and columns",
        description="Flip a table so rows become columns and columns become rows, or unpivot month columns into rows.",
        intro=["Transpose turns each row into a column and each column into a row, so a list of products down the side "
               "becomes a row of products across the top. Choose a column whose values name the new columns, such as "
               "Product, or let them be named Column 1, 2, 3.",
               "The same tool can also unpivot: when each month or year has its own column, it turns those columns into "
               "rows (one row per item per month), which is easier to total, filter and chart."],
        when=["A table that was typed the wrong way round.", "Products down the side that you want across the top.",
              "Monthly columns into a Month column, ready for a pivot table or chart (unpivot)."],
        steps=["Open the tool and choose your file.", "Choose Flip rows and columns, or Columns into rows.",
               "For a flip, choose the column that names the new columns. For columns into rows, choose the columns to "
               "keep as they are.", "Check the preview, then save."],
        example=Example(columns=["Product", "Jan", "Feb"], before=[["Tea", "120", "135"], ["Coffee", "90", "80"]],
                        after_columns=["Product", "Tea", "Coffee"], after=[["Jan", "120", "90"], ["Feb", "135", "80"]]),
        options=[("I want to", "Flip rows and columns (transpose), or turn columns into rows (unpivot)."),
                 ("New column names from", "Transpose: the column whose values become the new column names. Blank "
                  "values become Column 3 and so on, and repeats get (2)."),
                 ("Keep these as they are", "Unpivot: columns that stay as they are, such as Product."),
                 ("Names", "Unpivot: names for the new label and value columns.")],
        faqs=[("How many rows can I transpose?", "Up to 500, because each row becomes a column. Filter or keep fewer "
               "rows first for bigger files."),
              ("Are numbers kept as numbers?", "Yes. After the flip each column is checked again, so a column of numbers "
               "is a number column and a mixed column stays text."),
              ("What is the difference between transpose and unpivot?", "Transpose swaps the whole table. Unpivot keeps "
               "some columns, such as Product, and stacks the rest into two columns: a label (Jan, Feb) and a value."),
              ("Is unpivot the opposite of a pivot table?", "Yes, roughly. <a href=\"/tools/pivot-table\">Pivot "
               "table</a> goes from long to wide.")],
        related=["pivot-table", "rename-columns", "keep-top-rows"],
    ),
    # ------------------------------------------------------------------ convert
    ToolPage(
        slug="convert-file", op="convert", cat="convert", name="Convert file",
        title="Convert CSV, XLSX and JSON files, or save as PDF",
        description="Convert between CSV, XLSX (spreadsheet) and JSON, or save a table as a clean PDF with wrapped "
                    "text and Hindi support. Free, on your phone or computer.",
        intro=[
            "Convert file opens CSV, TSV, XLSX, XLS, JSON and NDJSON files and saves them as XLSX, CSV, JSON or PDF.",
            "CSV files include a marker so spreadsheet apps show accents and ₹ correctly. XLSX files keep long IDs "
            "exact and write numbers without accounting formats. PDFs wrap long text inside each column.",
        ],
        when=["Opening a CSV properly in a spreadsheet app.", "Sending a table as a PDF.", "Turning JSON into a spreadsheet."],
        steps=["Open the tool and choose your file.", "Pick the format to save as.", "Download, or share straight from your phone."],
        example=None,
        options=[("Save as", "Spreadsheet (.xlsx), CSV, JSON or PDF."),
                 ("PDF page", "Auto (landscape when there are many columns), portrait or landscape."),
                 ("PDF title", "Your own title on the first page; the file name is used if empty."),
                 ("PDF columns", "All columns, or only the ones you choose.")],
        faqs=[("Is there a size limit?", "Files up to 100 MB. A PDF shows up to 10,000 rows; use XLSX or CSV for more."),
              ("Which sheet is used from a workbook?", "The first one; you can switch sheets on the file card.")],
        related=["split-into-pages", "remove-columns"],
    ),
    ToolPage(
        slug="split-into-pages", op="split_pages", cat="convert", name="Split into pages",
        title="Split a spreadsheet by a column or every N rows",
        description="Split one file into parts: one per value of a column such as City, or every N rows. Get sheets in "
                    "one workbook, pages in one PDF, or separate CSV, XLSX or PDF files in a .zip.",
        intro=["Split into pages makes a part for each value in a column — the quick way to send each branch, "
               "salesperson or region only its own rows — or a part for every N rows, for sites that limit upload size.",
               "Parts can be sheets in one .xlsx, pages in one PDF, or separate files (CSV, XLSX or PDF) in a .zip."],
        when=["One sheet per branch from a company-wide report.", "A printable PDF with a page per class or team.",
              "Files of 10,000 rows each for a portal with an upload limit."],
        steps=["Open the tool and choose your file.", "Choose <b>By a column</b> and pick it, or <b>Every N rows</b> and type N.",
               "Choose sheets, PDF pages, or separate files, then download."],
        example=None,
        options=[("Split", "By a column (values sorted A→Z, blanks last) or every N rows."),
                 ("Save as", "Sheets (.xlsx), PDF pages, or separate files in a .zip (CSV, XLSX or PDF)."),
                 ("Limit", "Up to 200 parts.")],
        faqs=[("What if a value is too long for a sheet name?", "Sheet names are shortened and kept unique automatically.")],
        related=["filter-rows", "convert-file", "pivot-table"],
    ),
]

# --------------------------------------------------------------------------- one search per page
#
# Each tool page answers one search: the phrase people type goes in the <title>, the <h1> and
# the first paragraph. Other products are named only to say what files and tasks Gridglass handles
# (see TRADEMARKS); our own tool names stay neutral.

SEARCH: dict[str, tuple[str, str, str]] = {  # slug: (phrase, first paragraph, meta description)
    "remove-duplicates": (
        "Remove duplicate rows from a CSV or Excel file",
        "Remove duplicate rows from a CSV or Excel file in a few taps: choose which columns decide a duplicate, keep "
        "the first or last copy, and download a clean file. It works on your phone or computer, with no sign-up.",
        "Remove duplicate rows from a CSV or Excel file online. Match on all or chosen columns, keep the first or last "
        "copy, or just mark them. Free."),
    "trim-spaces": (
        "Remove extra spaces from CSV and Excel files",
        "Remove extra spaces from CSV and Excel files: spaces before and after text, and double spaces inside it, "
        "across whole columns at once, without a TRIM formula.",
        "Remove extra spaces from CSV and Excel files online: leading, trailing and double spaces in whole columns. "
        "Fixes filters and lookups that don't match. Free."),
    "change-case": (
        "Change text to uppercase, lowercase or proper case",
        "Change text to uppercase, lowercase or proper case (Title Case) in whole columns of a CSV or Excel file, so "
        "names, cities and codes are written one way.",
        "Change text to uppercase, lowercase or proper case online, for whole columns of a CSV or Excel file. Free, "
        "no formulas, works on phones."),
    "replace-values": (
        "Find and replace in CSV and Excel files",
        "Find and replace in CSV and Excel files, whole cells or part of the text, in the columns you choose. It also "
        "cleans text: remove special characters, keep only digits, or pull out an email's domain.",
        "Find and replace in CSV and Excel files online, or clean up text: remove special characters, keep only "
        "digits or letters, email domains. Free."),
    "fill-blanks": (
        "Fill blank cells with the value above",
        "Fill blank cells with the value above (fill down), with the value below, or with something you type such as "
        "0 or ‘Unknown’, across whole columns of a CSV or Excel file.",
        "Fill blank cells with the value above (fill down) or a value like 0, across whole columns of a CSV or Excel "
        "file. Free and online."),
    "remove-blank-rows": (
        "Delete blank rows from a CSV or Excel file",
        "Delete blank rows from a CSV or Excel file: rows that are completely empty, or rows missing something "
        "important such as an email or amount.",
        "Delete blank rows from a CSV or Excel file online: empty rows, or rows missing a value in columns you choose. "
        "Free, works on phones."),
    "filter-rows": (
        "Filter rows in a CSV or Excel file",
        "Filter rows in a CSV or Excel file and download only the rows you need: by text, numbers, dates or blanks, "
        "with values suggested from your own data.",
        "Filter rows in a CSV or Excel file online by text, numbers, dates or blanks, with up to 20 conditions. "
        "Download the result. Free."),
    "sort-rows": (
        "Sort a CSV file by multiple columns",
        "Sort a CSV file by multiple columns: by one column first, then by others to break ties, with numbers and "
        "dates sorted properly. Excel files work too.",
        "Sort a CSV file by multiple columns online, A to Z or largest first, with numbers and dates sorted "
        "correctly. Excel files work too. Free."),
    "remove-columns": (
        "Delete columns from a CSV file",
        "Delete columns from a CSV file by tapping them, then download a smaller, cleaner file. Excel and JSON files "
        "work too.",
        "Delete columns from a CSV file online by tapping them. Excel and JSON files work too. Free, no sign-up."),
    "choose-columns": (
        "Reorder columns in a CSV file",
        "Reorder columns in a CSV file by tapping them in the order you want, and leave out the rest. Excel files "
        "work too.",
        "Reorder columns in a CSV file online: tap columns in the order you want and drop the others. Excel files "
        "work too. Free."),
    "rename-columns": (
        "Rename column headers in a CSV file",
        "Rename column headers in a CSV file: type a new name next to any column and download. Excel files work too.",
        "Rename column headers in a CSV file online, for clearer reports or to match another file. Excel files work "
        "too. Free."),
    "keep-top-rows": (
        "Keep the first or last N rows of a CSV file",
        "Keep the first or last N rows of a CSV file, such as the top 10 after sorting, and download just those.",
        "Keep the first or last N rows of a CSV file online, such as a top 10 after sorting. Excel files work too. "
        "Free."),
    "change-type": (
        "Convert text to numbers in CSV and Excel files",
        "Convert text to numbers in CSV and Excel files, or text to dates, so totals, sorting and filters work. "
        "Amounts like ‘₹1,23,456’ are usually read as numbers automatically.",
        "Convert text to numbers in CSV and Excel files online (or text to dates), so totals and sorting work. "
        "Handles ₹ and Indian commas. Free."),
    "split-column": (
        "Split one column into multiple columns",
        "Split one column into multiple columns at a comma, space or any separator, such as a full name into first "
        "and last name.",
        "Split one column into multiple columns online by comma, space or any separator, like full name into first "
        "and last name. Free."),
    "add-column": (
        "Add a calculated column without formulas",
        "Add a calculated column without formulas: if-then rules, part of a text (first or last characters, text "
        "before or after a symbol), the month or financial year of a date, number ranges, totals and ranks, or "
        "simple math between columns.",
        "Add a calculated column without formulas: if-then rules, text before/after, first/last characters, date "
        "parts, ranges, running totals, rank, % of total or math. Free, online."),
    "merge-files": (
        "Merge two CSV files by a common column",
        "Merge two CSV files by a common column, such as Order ID or Email, and bring over the columns you need. "
        "If you know VLOOKUP, it does the same job without formulas, and Excel files work too.",
        "Merge two CSV files by a common column online, like a VLOOKUP without formulas. Every join type; Excel "
        "files work too. Free."),
    "stack-files": (
        "Combine multiple CSV files into one",
        "Combine multiple CSV files into one by putting their rows one under another, even when the columns are in a "
        "different order. Excel files work too.",
        "Combine multiple CSV files into one online, matching columns by name. Add a column for the source file. "
        "Excel files work too. Free."),
    "pivot-table": (
        "Create a pivot table from a CSV file",
        "Create a pivot table from a CSV file online: group by any column, add up or count values, spread totals "
        "across columns and add a Grand Total. Excel files work too.",
        "Create a pivot table from a CSV file online: group, sum, count, filter and chart. Excel files work too. "
        "Free, works on phones."),
    "make-a-chart": (
        "Make a chart from CSV or Excel data",
        "Make a chart from CSV or Excel data in a few taps: choose what to group by and what to add up, then pick "
        "column, bar, line, area, pie or donut.",
        "Make a chart from CSV or Excel data online: column, bar, line, area, pie or donut, with titles, colours and "
        "data labels. Download PNG or SVG."),
    "transpose": (
        "Transpose rows and columns in a CSV or Excel file",
        "Transpose rows and columns in a CSV or Excel file: each row becomes a column and each column becomes a row.",
        "Transpose rows and columns in a CSV or Excel file online, or unpivot month columns into rows. Free, works on "
        "phones."),
    "convert-file": (
        "Convert Excel files to CSV online",
        "Convert Excel files to CSV online, keeping long IDs exact and Indian text readable. It also converts CSV to "
        "Excel, either one to JSON, and any of them to a clean PDF.",
        "Convert Excel files to CSV online, or CSV to Excel, JSON or PDF. Long IDs stay exact. Free, no sign-up, "
        "works on phones."),
    "split-into-pages": (
        "Split an Excel sheet into multiple sheets by column value",
        "Split an Excel sheet into multiple sheets by column value, such as one sheet per city or branch, or into "
        "files of N rows each. CSV files work too.",
        "Split an Excel sheet into multiple sheets by column value online, or into separate files of N rows. PDF "
        "pages too. Free."),
}


def _for_search(t: ToolPage) -> ToolPage:
    from dataclasses import replace

    phrase, lead, description = SEARCH[t.slug]
    return replace(t, title=phrase, description=description, intro=[lead, *t.intro])


TOOLS = [_for_search(t) for t in TOOLS]
MOVED = {"unpivot": "transpose"}  # old tool page addresses, forwarded permanently
TOOL_BY_SLUG = {t.slug: t for t in TOOLS}

#: Shown on every information page. Other products are named only to describe what Gridglass works with.
TRADEMARKS = ("Microsoft and Excel are trademarks of the Microsoft group of companies. Google Sheets is a trademark "
              "of Google LLC. Gridglass is independent and is not affiliated with, endorsed by or sponsored by "
              "Microsoft or Google.")


# --------------------------------------------------------------------------- guides

@dataclass(frozen=True)
class Guide:
    slug: str
    title: str
    description: str
    sections: list[tuple[str, list[str]]]   # (heading, paragraphs/lists as HTML)
    tools: list[str]                         # tool slugs used


GUIDES: list[Guide] = [
    Guide(
        slug="combine-monthly-reports",
        title="How to combine monthly reports into one file",
        description="Put twelve monthly CSV or spreadsheet reports into one table, even when columns are in a different "
                    "order, then total them by month.",
        sections=[
            ("The problem", [
                "Many systems export one file per month or per branch. To see the year, or compare branches, you need "
                "them in one table, and copying and pasting twelve files is slow and easy to get wrong.",
            ]),
            ("Stack the files", [
                "<ol><li>Open <a href=\"/tools/stack-files\">Stack files</a> and choose January's file.</li>"
                "<li>Under <b>Files to add</b>, choose the other eleven files at once.</li>"
                "<li>Turn on <b>Add a column saying which file each row came from</b>, and call it <i>Month file</i>.</li>"
                "<li>Check the preview: the badge shows how many rows were added.</li></ol>",
                "Columns are matched by name, ignoring capitals and extra spaces. If one month added a new column, "
                "the other months are simply blank there.",
            ]),
            ("Clean and summarise", [
                "Exports sometimes repeat rows at month boundaries. Run <a href=\"/tools/remove-duplicates\">Remove "
                "duplicates</a> using the order ID column. Then make a <a href=\"/tools/pivot-table\">Pivot table</a> with "
                "<i>Month file</i> as Rows and <i>Sum of Amount</i> as the Value, and switch to Chart for a quick picture.",
            ]),
            ("Do it again next year in one tap", [
                "On the result screen, tap <b>Save these steps as a recipe</b>. Next year, open the recipe from the "
                "home screen: it asks for each month's file in turn, then stacks, cleans and summarises them in one go.",
            ]),
        ],
        tools=["stack-files", "remove-duplicates", "pivot-table"],
    ),
    Guide(
        slug="clean-a-customer-list",
        title="How to clean a customer list in five minutes",
        description="Fix stray spaces, mixed capitals, blank rows and duplicate contacts in a customer or contact list, "
                    "step by step.",
        sections=[
            ("Why lists get messy", [
                "Lists typed by several people, or copied from forms, end up with ‘ asha@example.com’, ‘ASHA RAO’, empty "
                "rows and the same person twice. Each problem is small, but together they spoil mailings and counts.",
            ]),
            ("Start with a check", [
                "In the app, tap <b>Check</b> on the file card. Gridglass looks at every row and lists what needs "
                "attention: exact copies, blank rows, stray spaces, the same value written differently and columns that "
                "are almost all numbers. Many problems have a one-tap fix right there.",
            ]),
            ("The order that works", [
                "<ol><li><a href=\"/tools/trim-spaces\">Trim spaces</a> on all text columns.</li>"
                "<li><a href=\"/tools/change-case\">Change case</a>: emails to lower, names to Title.</li>"
                "<li><a href=\"/tools/remove-blank-rows\">Remove blank rows</a> where the email is blank.</li>"
                "<li><a href=\"/tools/remove-duplicates\">Remove duplicates</a> by email, keeping the last copy so the "
                "newest details win.</li></ol>",
                "Doing it in this order matters: trimming and changing case first means duplicates that differ only by "
                "a space or a capital letter are caught.",
            ]),
            ("Save it as a recipe", [
                "After the last step, tap <b>Save these steps as a recipe</b>. Next time, open the recipe from the home "
                "screen, choose the new list, and all four steps run at once.",
            ]),
        ],
        tools=["trim-spaces", "change-case", "remove-blank-rows", "remove-duplicates"],
    ),
    Guide(
        slug="look-up-values-from-another-file",
        title="How to look up values from another file",
        description="Add columns from a second spreadsheet by matching an ID, email or name, and find rows that have "
                    "no match, without writing formulas.",
        sections=[
            ("What a lookup does", [
                "You have orders with a City column, and a separate list that gives each City's Region. A lookup adds "
                "the Region to every order by matching the City in both files.",
            ]),
            ("Step by step", [
                "<ol><li>Open <a href=\"/tools/merge-files\">Merge files</a> and choose the orders file.</li>"
                "<li>Add the second file. Gridglass suggests matching columns with the same name.</li>"
                "<li>Keep <b>All rows here + matches</b>, and choose the columns to bring in.</li>"
                "<li>Check the preview. Rows without a match show blank cells in the new columns.</li></ol>",
            ]),
            ("Finding what's missing", [
                "Choose <b>Only rows with no match</b> to list orders whose city isn't in the second file, or payments "
                "that don't match any invoice. It's a quick way to reconcile two lists.",
            ]),
            ("When matches fail", [
                "Most failed matches are hidden spaces or different capitals. Run <a href=\"/tools/trim-spaces\">Trim "
                "spaces</a> and <a href=\"/tools/change-case\">Change case</a> on the matching column in both files first.",
            ]),
        ],
        tools=["merge-files", "trim-spaces", "change-case"],
    ),
    Guide(
        slug="one-sheet-per-branch",
        title="How to send each branch only its own rows",
        description="Split one big spreadsheet into a workbook with one sheet per branch, city or salesperson, or a PDF "
                    "with one page each.",
        sections=[
            ("The idea", [
                "A head office report has every branch in one table. Each branch manager only needs their rows. "
                "Instead of filtering and copying twenty times, split the file once.",
            ]),
            ("Step by step", [
                "<ol><li>Clean up first if needed: <a href=\"/tools/sort-rows\">sort</a> by date and "
                "<a href=\"/tools/remove-columns\">remove columns</a> that are internal.</li>"
                "<li>Open <a href=\"/tools/split-into-pages\">Split into pages</a> and choose the Branch column.</li>"
                "<li>Choose .xlsx for one sheet per branch, or PDF for one page per branch.</li></ol>",
            ]),
            ("Only one branch?", [
                "Use <a href=\"/tools/filter-rows\">Filter rows</a> with ‘Branch is Rohini’, then download.",
            ]),
        ],
        tools=["split-into-pages", "filter-rows", "remove-columns"],
    ),
    Guide(
        slug="fix-numbers-stored-as-text",
        title="Why your numbers won't add up, and how to fix them",
        description="Amounts with ₹ signs, commas, ‘N/A’ or brackets are read as text, so totals and sorting fail. "
                    "Here's how Gridglass reads them, and what to do when it can't.",
        sections=[
            ("What Gridglass already handles", [
                "When you open a file, Gridglass reads amounts the way people type them: ‘₹1,23,456.50’, ‘Rs. 500/-’, "
                "‘$1,234’ and ‘(250)’ for minus 250, with Indian or western comma grouping. Dates like ‘05/03/2026’, "
                "‘5 Mar 2026’ and ‘March 5, 2026’ become real dates; day comes first unless the column shows otherwise.",
                "A column only becomes numbers when <b>every</b> cell fits, so one stray word keeps the whole column as "
                "text. That's deliberate: nothing is silently lost.",
            ]),
            ("When a column stays text", [
                "<ol><li>Look for the odd values: open <a href=\"/tools/filter-rows\">Filter rows</a> and type in the "
                "value box to see what's in the column.</li>"
                "<li>Clear placeholders such as ‘N/A’ or ‘-’ with <a href=\"/tools/replace-values\">Replace values</a>.</li>"
                "<li>Then use <a href=\"/tools/change-type\">Change type</a> to make the column a decimal number.</li></ol>",
            ]),
            ("Long IDs stay text on purpose", [
                "Whole numbers longer than 10 digits, and numbers starting with 0, are kept as text. Spreadsheet apps keep "
                "only 15 significant digits, so a 19-digit transaction ID would otherwise be changed for ever.",
            ]),
        ],
        tools=["replace-values", "change-type", "filter-rows"],
    ),
]

GUIDE_BY_SLUG = {g.slug: g for g in GUIDES}
