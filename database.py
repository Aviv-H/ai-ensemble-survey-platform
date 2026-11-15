import os
from datetime import datetime
from pymongo import MongoClient
from dotenv import load_dotenv

# טעינת משתני הסביבה (ה-URI של מונגו) מתוך קובץ ה-.env
load_dotenv()

# התחברות למונגו
MONGO_URI = os.getenv("MONGO_URI")

# הדפסת סטטוס לטרמינל
print("\n=== DEBUG INFO ===")
if MONGO_URI:
    print("Success! .env was read.")
    # מדפיס רק את 15 התווים הראשונים כדי לוודא שזה לא ריק, מבלי להדפיס את הסיסמה כולה
    print("Value starts with:", MONGO_URI[:15], "...")
else:
    print("Error: MONGO_URI is None. The .env file was NOT read properly.")
print("==================\n")


client = MongoClient(MONGO_URI)

# בחירת מסד הנתונים שיצרנו
db = client['thesis_study']


def get_all_questions():
    """
    שולף את כל 40 השאלות ממסד הנתונים.
    מחזיר רשימה של מילונים (Dictionaries).
    """
    return list(db.questions.find({}))


def get_distribution(distribution_id):
    """
    שולף התפלגות ספציפית לפי ה-ID שלה.
    """
    return db.support_distributions.find_one({"_id": distribution_id})


def create_or_get_participant(prolific_id, user_agent=""):
    """
    רושם משתתף חדש בניסוי כשהוא נכנס דרך הלינק של פרוליפיק.
    אם הוא בטעות רענן את הדף (והוא כבר קיים), זה לא ימחק אותו אלא רק יחזיר את הקיים.
    """
    participant = {
        "_id": prolific_id,
        "status": "IN_PROGRESS",
        "started_at": datetime.utcnow(),
        "completed_at": None,
        "user_agent": user_agent,
        "completion_code": None
    }

    # upsert=True אומר: אם לא קיים - תצור. אם קיים - אל תעשה כלום (כדי לא לדרוס את זמן ההתחלה)
    db.participants.update_one(
        {"_id": prolific_id},
        {"$setOnInsert": participant},
        upsert=True
    )

    return db.participants.find_one({"_id": prolific_id})


def update_participant_completed(prolific_id, completion_code, feedback_text=""):
    """
    מעדכן את הסטטוס של המשתתף ל"הושלם", ושומר את קוד הסיום וחוות הדעת (פידבק).
    """
    db.participants.update_one(
        {"_id": prolific_id},
        {
            "$set": {
                "status": "COMPLETED",
                "completed_at": datetime.utcnow(),
                "completion_code": completion_code,
                "feedback": feedback_text
            }
        }
    )


def save_response(response_data):
    """
    שומר רשומת תשובה (Response) בודדת של המשתמש עבור שאלה ספציפית.
    """
    # נוסיף חותמת זמן מדויקת מתי התשובה נשלחה
    response_data['submitted_at'] = datetime.utcnow()
    db.responses.insert_one(response_data)


def get_participant(prolific_id):
    """
    שולף משתתף קיים לפי מזהה ה-Prolific שלו.
    """
    return db.participants.find_one({"_id": prolific_id})


def get_participant_responses_count(prolific_id):
    """
    מחזיר כמה תשובות המשתמש כבר הגיש בפועל.
    """
    return db.responses.count_documents({"participant_id": prolific_id})


def reset_participant_responses(prolific_id):
    """
    מאפס את כל התשובות של המשתתף אם הוא בחר להתחיל מהתחלה.
    """
    # מחיקת כל התשובות הקודמות שלו
    db.responses.delete_many({"participant_id": prolific_id})

    # איפוס סטטוס וזמן התחלה
    db.participants.update_one(
        {"_id": prolific_id},
        {
            "$set": {
                "status": "IN_PROGRESS",
                "started_at": datetime.utcnow(),
                "completed_at": None,
                "completion_code": None
            }
        }
    )