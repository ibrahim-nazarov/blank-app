import streamlit as st
import pandas as pd

# Saytın ümumi tənzimləmələri
st.set_page_config(page_title="Təqaüd və ÜOMG Portalı", page_icon="🎓", layout="centered")

st.markdown("""
    <style>
    .block-container { padding-top: 2rem; padding-bottom: 2rem; }
    h1 { text-align: center; color: #1E3A8A; font-family: 'Helvetica Neue', sans-serif; }
    .stTextInput>div>div>input { text-align: center; font-size: 18px; letter-spacing: 2px; }
    </style>
""", unsafe_allow_html=True)

st.title("🎓 Tələbə Nəticə Portalı")
st.markdown("<p style='text-align: center; color: #6B7280;'>Təqaüd növünüzü və ÜOMG göstəricinizi öyrənmək üçün FİN kodunuzu daxil edin.</p>", unsafe_allow_html=True)
st.write("---")

# Sizin Google Sheets linkiniz
csv_url = "https://docs.google.com/spreadsheets/d/1vrVAitW-jsaRjn9qWEl4SI6J2iS6VI9toceTuesqfVU/export?format=csv"

@st.cache_data(ttl=15)
def load_data():
    try:
        data = pd.read_csv(csv_url)
        data.columns = data.columns.str.strip()
        return data
    except Exception as e:
        return None

df = load_data()

# Axtarış xanası
fin_input = st.text_input("🔑 FİN Kodunuzu yazın və Enter sıxın:", max_chars=7).strip().upper()

if fin_input:
    if df is not None:
        # Finkod sütununa görə axtarış
        user_data = df[df['Finkod'].astype(str).str.strip().str.upper() == fin_input]
        
        if not user_data.empty:
            ad_soyad = user_data.iloc[0]['Soyadı, adı və atasının adı']
            uomg = user_data.iloc[0]['ÜOMG']
            
            # DİQQƏT: Sütun adı cədvəldəki kimi bitişik yazılıb
            teqaud_raw = str(user_data.iloc[0]['Təqaüdforması']).strip()
            
            st.write("")
            st.markdown(f"### 👋 Salam, **{ad_soyad}**")
            
            if teqaud_raw.lower() == "əlaçı":
                st.balloons()
                st.success("🚀 **TƏBRİKLƏR! ƏLAÇI TƏQAÜDÜ ALIRSINIZ!** 🏆")
                st.info(f"🎯 Sizin ÜOMG göstəriciniz: **{uomg}**")
                st.write("🌟 Mükəmməl nəticə! Uğurlarınız daimi olsun! 🎉")
                
            elif teqaud_raw.lower() == "həvəsləndirici":
                st.balloons()
                st.info("✨ **TƏBRİKLƏR! HƏVƏSLƏNDİRİCİ TƏQAÜDÜ ALIRSINIZ!** 🎯")
                st.info(f"📊 Sizin ÜOMG göstəriciniz: **{uomg}**")
                st.write("⚡ Çox gözəl göstəricidir! Əlaçı olmağa çox az qalıb, uğurlar! 💪")
                
            elif teqaud_raw.lower() == "adi":
                st.balloons()
                st.warning("📚 **ADİ TƏQAÜD ALIRSINIZ!** 👍")
                st.info(f"📉 Sizin ÜOMG göstəriciniz: **{uomg}**")
                st.write("🙃 Təqaüd siyahısındasınız. Növbəti semestrdə daha da irəli! 🎯")
                
            else:
                st.error("🥺 **Təəssüf ki, bu semestr stipendiyaya düşmədiniz.**")
                st.info(f"📊 Sizin ÜOMG göstəriciniz: **{uomg}**")
                st.write("📚 Ruhdan düşməyin! Növbəti semestrdə mütləq daha yaxşı olacaq, çalışmaqda davam edin! 💪")
        else:
            st.error("❌ Daxil etdiyiniz FİN koda uyğun məlumat tapılmadı. Yenidən yoxlayın. 🧐")
    else:
        st.error("⚠️ Məlumat bazası ilə əlaqə kəsildi. Zəhmət olmasa Google Sheets sənədinin paylaşım tənzimləmələrini yoxlayın.")
