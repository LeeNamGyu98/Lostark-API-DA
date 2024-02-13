import re
import requests
import ast
import time
import json
import pymysql
import datetime
import urllib3
import pandas as pd
import traceback
import pprint
import joblib
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# connection 및 cursor 반환
def get_db_cursor():
    db = pymysql.connect(host = 'localhost', 
                     port = 3306, 
                     user='root', 
                     passwd = admin_key['password'],
                     charset='utf8')

    # Create a cursor object
    cursor = db.cursor()
    cursor.execute("USE lostark")
    return db, cursor

# db, api key
def get_admin_key():
    with open("C:\\Users\\user\\Code_Files_Jupyter\\Lostark\\Lostark-API-DA\\key.json", 'r') as file:
        return json.load(file)
    
#! eval은 보안에 위험한 코드이나 현 단계에서는 넘어감(문자로 된 것을 코드화 하는 함수)
def eval_data(resp):
    edata = resp.text
    replace_text = ["null", "false", "true"]
    if any(rt in edata for rt in replace_text):
        edata = edata.replace("null", "None")
        edata = edata.replace("false", "False")
        edata = edata.replace("true", "True")
    edata = eval(edata)
    return edata

# response preprocessing
def text_cleaner(t):
    br_cleaner = re.compile("<br>", re.I)
    html_cleaner = re.compile("<.*?>[ ]?")
    escape_cleaner = re.compile("\\\[rn]|\s\s")
    cleantext = re.sub(br_cleaner, " ", t)
    cleantext = re.sub(html_cleaner, "", cleantext)
    cleantext = re.sub(escape_cleaner, "", cleantext)
    cleantext = cleantext.strip()
    return cleantext

# db에서 characterCode의 마지막을 가져옴
def get_last_characterCode():
    db, cursor = get_db_cursor()
    cursor.execute("SELECT characterCode FROM lostark.raw_character_data_table ORDER BY characterCode DESC LIMIT 1")
    result = cursor.fetchone()
    db.close()
    if result is not None:
        return result[0]
    else:
        return 0

# db에서 characterName이 이미 들어가 있는지 확인
def check_name_already_in(characterName):
    db, cursor = get_db_cursor()
    sql = """
    SELECT COUNT(*) FROM lostark.raw_character_data_table WHERE characterName = %s;
    """
    cursor.execute(sql, (characterName,))
    db.close()
    return cursor.fetchone()

# db에 이미 입력된 데이터인지 확인
def check_code_already_in(table, characterCode):
    db, cursor = get_db_cursor()
    sql = f"SELECT COUNT(*) FROM lostark.{table} WHERE characterCode = %s;"
    cursor.execute(sql, (characterCode, ))
    db.close()
    return cursor.fetchone()

# 테이블 삭제
def delete_table(table):
    db, cursor = get_db_cursor()
    sql = f'DELETE FROM lostark.{table}_table;'
    cursor.execute(sql)
    db.commit()
    db.close()

# API 응답이 None일 경우 삭제
def remove_characterName(characterName_list, idx, error):
    with open("C:\\Users\\user\\Code_Files_Jupyter\\Lostark\\Lostark-API-DA\\character\\removed_characterName_list.txt", "a", encoding="utf-8") as f:
        f.write(str(characterName_list[idx]) + f": {error}\n")
    characterName_list.remove(characterName_list[idx])
    with open("C:\\Users\\user\\Code_Files_Jupyter\\Lostark\\Lostark-API-DA\\character\\characterName_list.txt", "w", encoding="utf-8") as f:
        f.write(str(characterName_list))

# character API 호출
def get_character_responses(characterName):
    url = 'https://developer-lostark.game.onstove.com/characters/{}/siblings'.format(characterName) 
    # request character data, 갑자기 인증 에러로 verify = False로 지정
    resp = requests.get(url=url, headers=headers, timeout=timeout, verify = False)
    time.sleep(duration)
    return eval_data(resp)

# profile API 호출
def get_total_profile_responses(characterName):
    url = 'https://developer-lostark.game.onstove.com/armories/characters/{}'.format(characterName) 
    resp = requests.get(url=url, headers=headers, timeout=timeout, verify = False)
    resp = eval_data(resp)
    resp = text_cleaner(str(resp))
    profiles_responses = ast.literal_eval(resp)
    time.sleep(duration)
    if profiles_responses != None:
        return profiles_responses
    return None

# db에 삽입하기 위한 values 반환
def get_profile_values(profile_responses):
    characterName = profile_responses['ArmoryProfile']['CharacterName']
    characterCode = get_last_characterCode()
    characterCode += 1
    values = [characterCode, characterName]
    for part in profile_responses:
        values.append(str(profile_responses[part]))
    return values

# raw_character_table(db)에 삽입
def insert_raw_character_data(values):
    result = check_name_already_in(values[1])
    if result[0] == 1: return None

    db, cursor = get_db_cursor()
    try:
        # insert data
        sql = """
        INSERT INTO lostark.raw_character_data_table (characterCode, CharacterName, ArmoryProfile, ArmoryEquipment,ArmoryAvatars, ArmorySkills,
        ArmoryEngraving, ArmoryCard, ArmoryGem, ColosseumInfo, Collectibles) 
        VALUES (%s, %s, %s, %s, %s, %s, 
        %s, %s, %s, %s, %s);
        """
        cursor.execute(sql, values)
        db.commit()

    except Exception as e:
        # Rollback if there is any error
        db.rollback()
        print("Error inserting record:", e)
        print("Current time:", datetime.datetime.now())
    db.close()

# 최초 삽입 작업 이후 추가입력되는 character를 db에 삽입하기 위한 함수
def insert_character_data(characterName):
    resp = get_character_responses(characterName)
    for character in resp: # sub character
        profile_responses = get_total_profile_responses(character['CharacterName'])
        if profile_responses != None:
            values = get_profile_values(profile_responses)
            insert_raw_character_data(values) # 전처리 전
            character_df = get_df_all_raw_table(character['CharacterName'])
            insert_all_table(character_df) # 전처리 후

# 전처리 전 db의 table에서 특정 column의 값을 반환
def get_df_raw_table(column, idx=-1):
    db, cursor = get_db_cursor()
    if idx != -1:
        sql = f"SELECT characterCode, {column} FROM lostark.raw_character_data_table LIMIT {idx}, 5000"
    else:
        sql = f"SELECT characterCode, {column} FROM lostark.raw_character_data_table"
        
    cursor.execute(sql)
    df = pd.DataFrame(cursor.fetchall(), columns=['characterCode', 'data'])
    db.close()
    return df

# 한 캐릭터의 전체 raw_table 값 반환
def get_df_all_raw_table(characterName):
    db, cursor = get_db_cursor()
    sql = "SHOW COLUMNS FROM lostark.raw_character_data_table"
    cursor.execute(sql)
    column_names = [column[0] for column in cursor.fetchall()]

    sql = f"SELECT * FROM lostark.raw_character_data_table WHERE characterName = '{characterName}'"
    cursor.execute(sql)
    df = pd.DataFrame(cursor.fetchall(), columns=column_names)
    db.close()
    return df

# 전처리한 table에서 df 반환
def get_table_df(tableName, characterName=''):
    db, cursor = get_db_cursor()
    sql = f"SHOW COLUMNS FROM lostark.{tableName}"
    cursor.execute(sql)
    column_names = [column[0] for column in cursor.fetchall()]
    if characterName == '':
        sql = f"SELECT * FROM lostark.{tableName}"
    else:
        sql = f"SELECT * FROM lostark.{tableName} WHERE characterName = '{characterName}'"
    cursor.execute(sql)
    df = pd.DataFrame(cursor.fetchall(), columns=column_names)
    db.close()
    return df

# API 호출시 비정렬된 값을 정렬
def flatten_dict(d, parent_key='', sep='_'):
    items={}
    for k, v in d.items():
        new_key = parent_key + sep + k if parent_key else k
        try:
            v = eval(v)
        except:
            pass
        
        if isinstance(v, dict):
            items.update(flatten_dict(v, new_key, sep))
        else:
            items[new_key] = v
    return items

# 전처리 과정 중 에러 발생시
def print_preprocessing_exception(fd, sk, sv, e):
    traceback.print_exc()
    pprint(fd)
    print(sk, sv, "\n", e)

# db삽입 과정 중 에러 발생시
def print_insert_db_exception(value, e):
    traceback.print_exc()
    print("Error inserting record:", e)
    print("characterCode:", value['characterCode'])
    pprint(value)
    print("Current time:", datetime.datetime.now())

# sql 삽입할 때 values = [] 안의 내용
def get_sql_value(value, tableName):
    return tableName + "['" + value + "']" 
def print_sql_values(table, tableName):
    return ''.join(f'{get_sql_value(k, tableName)}, ' for k in table.keys())[:-2]


# API setup
admin_key = get_admin_key()
headers = {'Authorization': 'Bearer {}'.format(admin_key['api-key'])}
timeout = 10
#api 분당 100회 제한
duration = 60 / 90



### 1. profile, stats ###
def insert_profile_stats_table(characterCode, data):
    result = check_code_already_in("profile_table", characterCode)
    if result[0] == 1: return

    ## stats keys
    stats = {'characterCode' : None,
                '치명_값':None, '치명_내실증가량':None, '치명_치명타_적중률(%)':None,
                '특화_값':None, '특화_내실증가량':None, '특화_각성스킬_피해량(%)':None, '특화_효과1':None,
                '특화_효과2':None, '특화_효과3':None,
                '제압_값':None, '제압_내실증가량':None, '제압_피해증가량(%)':None,
                '신속_값':None, '신속_내실증가량':None, '신속_공격속도(%)':None, '신속_이동속도(%)':None,
                '신속_스킬_재사용대기시간_감소율(%)':None,
                '인내_값':None, '인내_내실증가량': None, '인내_물리방어력(%)':None, '인내_마법방어력(%)':None,
                '인내_보호막효과(%)':None, '인내_생명력_회복효과(%)':None,
                '숙련_값':None, '숙련_내실증가량':None, '숙련_상태이상_공격_지속시간(%)':None,
                '숙련_상태이상_피해_지속시간(%)':None, '숙련_무력화_피해량(%)':None,
                '최대생명력_값':None, '최대생명력_체력':None, '최대생명력_생명활성력(%)':None,
                '공격력_값':None, '공격력_기본공격력':None, '공격력_증감량':None}

    cdf = eval(data)
    del cdf['CharacterImage']
    
    ## Preprocessing profile and stat row data
    # 1. profile
    profile = cdf.copy()
    profile['characterCode'] = characterCode
    profile['ItemAvgLevel'] = float(profile['ItemAvgLevel'].replace(',', ''))
    profile['ItemMaxLevel'] = float(profile['ItemMaxLevel'].replace(',', ''))
    if profile['ServerName'] == '':
        profile['ServerName'] = None
    profile['지성'] = profile['Tendencies'][0]['Point']
    profile['담력'] = profile['Tendencies'][1]['Point']
    profile['매력'] = profile['Tendencies'][2]['Point']
    profile['친절'] = profile['Tendencies'][3]['Point']
    
    del profile['Tendencies']
    del profile['Stats']
    
    # 2. stats
    stat = stats.copy()
    stat['characterCode'] = characterCode
    for k, v in cdf.items():
        if (k == 'Stats') & (v != None):
            stat['치명_값'] = int(v[0]['Value'])
            stat['치명_내실증가량'] = int(int_pattern.findall(v[0]['Tooltip'][1])[0])
            stat['치명_치명타_적중률(%)'] = float(float_pattern.search(v[0]['Tooltip'][0]).group())

            stat['특화_값'] = int(v[1]['Value'])
            stat['특화_내실증가량'] = int(int_pattern.findall(v[1]['Tooltip'][-2])[0])
            try: # 전직 했을 경우
                stat['특화_각성스킬_피해량(%)'] = float(float_pattern.search(v[1]['Tooltip'][-3]).group())
                stat['특화_효과1'] = v[1]['Tooltip'][0]
                stat['특화_효과2'] =  v[1]['Tooltip'][1]
                stat['특화_효과3'] = None if len(v[1]['Tooltip']) == 5 else v[1]['Tooltip'][2]
            except: # 전직 안했을 경우
                pass
            

            stat['제압_값'] = int(v[2]['Value'])
            stat['제압_내실증가량'] = int(int_pattern.findall(v[2]['Tooltip'][2])[0])
            stat['제압_피해증가량(%)'] = float(float_pattern.search(v[2]['Tooltip'][0]).group())

            stat['신속_값'] = int(v[3]['Value'])
            stat['신속_내실증가량'] =  int(int_pattern.findall(v[3]['Tooltip'][-2])[0])
            stat['신속_공격속도(%)'] = float(float_pattern.search(v[3]['Tooltip'][0]).group())
            stat['신속_이동속도(%)'] = float(float_pattern.search(v[3]['Tooltip'][1]).group())
            stat['신속_스킬_재사용대기시간_감소율(%)'] = float(float_pattern.search(v[3]['Tooltip'][2]).group())

            stat['인내_값'] = int(v[4]['Value'])
            stat['인내_내실증가량'] = int(int_pattern.findall(v[4]['Tooltip'][-2])[0])
            stat['인내_물리방어력(%)'] = float(float_pattern.search(v[4]['Tooltip'][0]).group())
            stat['인내_마법방어력(%)'] = float(float_pattern.search(v[4]['Tooltip'][1]).group())
            stat['인내_보호막효과(%)'] =  float(float_pattern.search(v[4]['Tooltip'][2]).group())
            stat['인내_생명력_회복효과(%)'] = float(float_pattern.search(v[4]['Tooltip'][3]).group())

            stat['숙련_값'] =  int(v[5]['Value'])
            stat['숙련_내실증가량'] = int(re.findall(r'\d+', v[5]['Tooltip'][-2])[0])
            stat['숙련_상태이상_공격_지속시간(%)'] = float(float_pattern.search(v[5]['Tooltip'][0]).group())
            stat['숙련_상태이상_피해_지속시간(%)'] =  float(float_pattern.search(v[5]['Tooltip'][1]).group())
            stat['숙련_무력화_피해량(%)'] = float(float_pattern.search(v[5]['Tooltip'][2]).group())

            stat['최대생명력_값'] = int(v[6]['Value'])
            stat['최대생명력_체력'] = int(int_pattern.findall(v[6]['Tooltip'][1])[0])
            stat['최대생명력_생명활성력(%)'] = float(float_pattern.search(v[6]['Tooltip'][2]).group())

            stat['공격력_값'] = int(v[7]['Value'])
            stat['공격력_기본공격력'] =  int(int_pattern.findall(v[7]['Tooltip'][1])[0])
            stat['공격력_증감량'] = int(int_pattern.findall(v[7]['Tooltip'][2])[0])

    ## Insert DB
    # profile table
    try:  
        db, cursor = get_db_cursor()
        sql = """
            INSERT INTO lostark.profile_table (characterCode, expeditionLevel, pvpGradeName, townLevel, 
            title, guildMemberGrade, guildName, usingSkillPoint, totalSkillPoint, 지성, 담력, 매력, 친절,
            serverName, characterName, characterLevel, characterClassName, itemAvgLevel, itemMaxLevel)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
            """
        
        values = [profile['characterCode'], 
                  profile['ExpeditionLevel'], profile['PvpGradeName'], profile['TownLevel'],
                  profile['Title'], profile['GuildMemberGrade'], profile['GuildName'], 
                  profile['UsingSkillPoint'], profile['TotalSkillPoint'], 
                  profile['지성'], profile['담력'], profile['매력'], profile['친절'], 
                  profile['ServerName'], profile['CharacterName'], profile['CharacterLevel'], 
                  profile['CharacterClassName'], profile['ItemAvgLevel'], profile['ItemMaxLevel']]
        cursor.execute(sql, values)
        db.commit()
    except Exception as e:
        db.rollback()
        db.close()
        print_insert_db_exception(profile, e)
        raise e
    
    # stats_table
    try:  
        sql = """ INSERT INTO lostark.stats_table(characterCode,
            치명_값, 치명_내실증가량, `치명_치명타_적중률(%%)`,
            특화_값, 특화_내실증가량, `특화_각성스킬_피해량(%%)`, 특화_효과1, 특화_효과2, 특화_효과3,
            제압_값, 제압_내실증가량, `제압_피해증가량(%%)`,
            신속_값, 신속_내실증가량, `신속_공격속도(%%)`, `신속_이동속도(%%)`, `신속_스킬_재사용대기시간_감소율(%%)`,
            인내_값, 인내_내실증가량, `인내_물리방어력(%%)`, `인내_마법방어력(%%)`, `인내_보호막효과(%%)`, 
            `인내_생명력_회복효과(%%)`, 숙련_값, 숙련_내실증가량, `숙련_상태이상_공격_지속시간(%%)`, 
            `숙련_상태이상_피해_지속시간(%%)`, `숙련_무력화_피해량(%%)`, 최대생명력_값, 최대생명력_체력, 
            `최대생명력_생명활성력(%%)`, 공격력_값, 공격력_기본공격력, 공격력_증감량)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
        
        values = [stat['characterCode'], stat['치명_값'], stat['치명_내실증가량'], stat['치명_치명타_적중률(%)'],
          stat['특화_값'], stat['특화_내실증가량'], stat['특화_각성스킬_피해량(%)'],
          stat['특화_효과1'], stat['특화_효과2'], stat['특화_효과3'],
          stat['제압_값'], stat['제압_내실증가량'], stat['제압_피해증가량(%)'],
          stat['신속_값'], stat['신속_내실증가량'], stat['신속_공격속도(%)'], stat['신속_이동속도(%)'],
          stat['신속_스킬_재사용대기시간_감소율(%)'], stat['인내_값'], stat['인내_내실증가량'],
          stat['인내_물리방어력(%)'], stat['인내_마법방어력(%)'], stat['인내_보호막효과(%)'],
          stat['인내_생명력_회복효과(%)'], stat['숙련_값'], stat['숙련_내실증가량'],
          stat['숙련_상태이상_공격_지속시간(%)'], stat['숙련_상태이상_피해_지속시간(%)'],
          stat['숙련_무력화_피해량(%)'], stat['최대생명력_값'], stat['최대생명력_체력'],
          stat['최대생명력_생명활성력(%)'], stat['공격력_값'], stat['공격력_기본공격력'], stat['공격력_증감량']]

        cursor.execute(sql, values)
        db.commit()
        db.close()
    except Exception as e:
        db.rollback()
        db.close()
        print_insert_db_exception(stat, e)
        raise e

### 2. avatar  ###
def return_tendency(text, tendency):
    try:
        # "tendency : " 다음의 숫자 위치
        start_idx = text.find(f'{tendency} : ') + len(f'{tendency} : ')
        # 숫자가 시작하는 인덱스부터 숫자가 끝나는 인덱스까지 슬라이싱
        number = text[start_idx:].split()[0]
        return int(number)
    except:
        return None

def set_avatar(avatar, fd, parts):
    try:
        avatar[f'{parts}_grade'] = fd['Grade']
        avatar[f'{parts}_isInner'] = fd['IsInner']
        avatar[f'{parts}_isSet'] = fd['IsSet']
        avatar[f'{parts}_name'] = fd['Name']
        avatar[f'{parts}_avatarType'] = fd['Type']
        
        for k, v in fd.items():
            sk = str(k)
            sv = str(v)
            if (('희귀' in sv) | ('영웅' in sv) | ('전설' in sv)) & ('아바타' in sv): 
                avatar[f'{parts}_avatarType2'] = v
            elif ('전용' in sv) or ('계열' in sv):
                avatar[f'{parts}_availableClass'] = v
            elif '귀속' in sv:
                if (sv == '원정대 귀속됨 ') or (sv == '캐릭터 귀속됨') or ('(귀속)' in sv):
                    avatar[f'{parts}_attribution'] = True
                    avatar[f'{parts}_availableTrade'] = 0
                else:
                    avatar[f'{parts}_attribution'] = False
                    avatar[f'{parts}_availableTrade'] = int(int_pattern.findall(sv)[0])
            elif '+' in sv:
                avatar[f'{parts}_statEffect(%)'] = float(float_pattern.search(sv).group())
            elif ('매력' in sv) or ('지성' in sv) or ('담력' in sv) or ('친절' in sv):
                if ('매력' in sv):
                    avatar[f'{parts}_매력'] = return_tendency(sv, '매력')
                if ('지성' in sv):
                    avatar[f'{parts}_지성'] = return_tendency(sv, '지성')
                if ('담력' in sv):
                    avatar[f'{parts}_담력'] = return_tendency(sv, '담력')
                if ('친절' in sv):
                    avatar[f'{parts}_친절'] = return_tendency(sv, '친절')
            elif ('판매' in sv) or ('분해' in sv) or ('염색' in sv):
                avatar[f'{parts}_availableSale'] = '판매불가' not in sv
                avatar[f'{parts}_dyeable'] = '염색불가' not in sv
                avatar[f'{parts}_decomposable'] = '분해불가' not in sv
        return avatar
    except Exception as e:
        print_preprocessing_exception(fd, sk, sv, e)
        raise Exception("preprocessing error")
    
def insert_avatar_table(characterCode, data):
    result = check_code_already_in("avatar_table", characterCode)
    if result[0] == 1: return

    ## avatar keys
    avatar_parts = ['무기1', '무기2', '머리', '상의1', '상의2', '하의1', '하의2', '얼굴1', '얼굴2', '악기', '이동효과'] 
    dic_keys = ['grade', 'isInner', 'isSet', 'name', 'avatarType', 'avatarType2', 'availableClass', 
                'availableTrade', 'attribution', 'statEffect(%)', '매력', '지성', '담력', '친절', 'availableSale', 
                'dyeable', 'decomposable']
    avatars = {
        'characterCode': None,
    }
    for part in avatar_parts:
        for key in dic_keys:
            avatars[f'{part}_{key}'] = None


    avatar = avatars.copy()
    avatar['characterCode'] = characterCode
    cdf = eval(data)
    if cdf == None: return
        
    weapon_num = 0
    top_num = 0
    bottom_num = 0

    try:
        for j in range(len(cdf)):
            fd = flatten_dict(cdf[j])
            avatar_type = fd['Type']
            if avatar_type == '무기 아바타':
                weapon_num += 1
                avatar = set_avatar(avatar, fd, f'무기{weapon_num}')
            elif avatar_type == '상의 아바타':
                top_num += 1
                avatar = set_avatar(avatar, fd, f'상의{top_num}')
            elif avatar_type == '하의 아바타':
                bottom_num += 1
                avatar = set_avatar(avatar, fd, f'하의{bottom_num}')
            elif avatar_type =='머리 아바타':
                avatar = set_avatar(avatar, fd, '머리')
            elif avatar_type =='얼굴1 아바타':
                avatar = set_avatar(avatar, fd, '얼굴1')
            elif avatar_type =='얼굴2 아바타':
                avatar = set_avatar(avatar, fd, '얼굴2')
            elif avatar_type =='악기 아바타':
                avatar = set_avatar(avatar, fd, '악기')
            elif avatar_type == '':
                avatar = set_avatar(avatar, fd, '이동효과') 
    except Exception as e:
        raise e
        
    ## Insert DB
    # avatar table
    try: 
        db, cursor = get_db_cursor()
        sql = f"""
            INSERT INTO lostark.avatar_table (
                {''.join(f'{key}, ' for key in avatars.keys())[:-2]})
            VALUES ({''.join('%s, ' for _ in range(len(avatars.keys())))[:-2]});
            """
        sql = re.sub(r"(\w+_statEffect)\(%\)", r"`\1(%%)`", sql)
        values = [avatar['characterCode'], avatar['무기1_grade'], avatar['무기1_isInner'], avatar['무기1_isSet'], avatar['무기1_name'], avatar['무기1_avatarType'], avatar['무기1_avatarType2'], avatar['무기1_availableClass'], avatar['무기1_availableTrade'], avatar['무기1_attribution'], avatar['무기1_statEffect(%)'], avatar['무기1_매력'], avatar['무기1_지성'], avatar['무기1_담력'], avatar['무기1_친절'], avatar['무기1_availableSale'], avatar['무기1_dyeable'], avatar['무기1_decomposable'], avatar['무기2_grade'], avatar['무기2_isInner'], avatar['무기2_isSet'], avatar['무기2_name'], avatar['무기2_avatarType'], avatar['무기2_avatarType2'], avatar['무기2_availableClass'], avatar['무기2_availableTrade'], avatar['무기2_attribution'], avatar['무기2_statEffect(%)'], avatar['무기2_매력'], avatar['무기2_지성'], avatar['무기2_담력'], avatar['무기2_친절'], avatar['무기2_availableSale'], avatar['무기2_dyeable'], avatar['무기2_decomposable'], avatar['머리_grade'], avatar['머리_isInner'], avatar['머리_isSet'], avatar['머리_name'], avatar['머리_avatarType'], avatar['머리_avatarType2'], avatar['머리_availableClass'], avatar['머리_availableTrade'], avatar['머리_attribution'], avatar['머리_statEffect(%)'], avatar['머리_매력'], avatar['머리_지성'], avatar['머리_담력'], avatar['머리_친절'], avatar['머리_availableSale'], avatar['머리_dyeable'], avatar['머리_decomposable'], avatar['상의1_grade'], avatar['상의1_isInner'], avatar['상의1_isSet'], avatar['상의1_name'], avatar['상의1_avatarType'], avatar['상의1_avatarType2'], avatar['상의1_availableClass'], avatar['상의1_availableTrade'], avatar['상의1_attribution'], avatar['상의1_statEffect(%)'], avatar['상의1_매력'], avatar['상의1_지성'], avatar['상의1_담력'], avatar['상의1_친절'], avatar['상의1_availableSale'], avatar['상의1_dyeable'], avatar['상의1_decomposable'], avatar['상의2_grade'], avatar['상의2_isInner'], avatar['상의2_isSet'], avatar['상의2_name'], avatar['상의2_avatarType'], avatar['상의2_avatarType2'], avatar['상의2_availableClass'], avatar['상의2_availableTrade'], avatar['상의2_attribution'], avatar['상의2_statEffect(%)'], avatar['상의2_매력'], avatar['상의2_지성'], avatar['상의2_담력'], avatar['상의2_친절'], avatar['상의2_availableSale'], avatar['상의2_dyeable'], avatar['상의2_decomposable'], avatar['하의1_grade'], avatar['하의1_isInner'], avatar['하의1_isSet'], avatar['하의1_name'], avatar['하의1_avatarType'], avatar['하의1_avatarType2'], avatar['하의1_availableClass'], avatar['하의1_availableTrade'], avatar['하의1_attribution'], avatar['하의1_statEffect(%)'], avatar['하의1_매력'], avatar['하의1_지성'], avatar['하의1_담력'], avatar['하의1_친절'], avatar['하의1_availableSale'], avatar['하의1_dyeable'], avatar['하의1_decomposable'], avatar['하의2_grade'], avatar['하의2_isInner'], avatar['하의2_isSet'], avatar['하의2_name'], avatar['하의2_avatarType'], avatar['하의2_avatarType2'], avatar['하의2_availableClass'], avatar['하의2_availableTrade'], avatar['하의2_attribution'], avatar['하의2_statEffect(%)'], avatar['하의2_매력'], avatar['하의2_지성'], avatar['하의2_담력'], avatar['하의2_친절'], avatar['하의2_availableSale'], avatar['하의2_dyeable'], avatar['하의2_decomposable'], avatar['얼굴1_grade'], avatar['얼굴1_isInner'], avatar['얼굴1_isSet'], avatar['얼굴1_name'], avatar['얼굴1_avatarType'], avatar['얼굴1_avatarType2'], avatar['얼굴1_availableClass'], avatar['얼굴1_availableTrade'], avatar['얼굴1_attribution'], avatar['얼굴1_statEffect(%)'], avatar['얼굴1_매력'], avatar['얼굴1_지성'], avatar['얼굴1_담력'], avatar['얼굴1_친절'], avatar['얼굴1_availableSale'], avatar['얼굴1_dyeable'], avatar['얼굴1_decomposable'], avatar['얼굴2_grade'], avatar['얼굴2_isInner'], avatar['얼굴2_isSet'], avatar['얼굴2_name'], avatar['얼굴2_avatarType'], avatar['얼굴2_avatarType2'], avatar['얼굴2_availableClass'], avatar['얼굴2_availableTrade'], avatar['얼굴2_attribution'], avatar['얼굴2_statEffect(%)'], avatar['얼굴2_매력'], avatar['얼굴2_지성'], avatar['얼굴2_담력'], avatar['얼굴2_친절'], avatar['얼굴2_availableSale'], avatar['얼굴2_dyeable'], avatar['얼굴2_decomposable'], avatar['악기_grade'], avatar['악기_isInner'], avatar['악기_isSet'], avatar['악기_name'], avatar['악기_avatarType'], avatar['악기_avatarType2'], avatar['악기_availableClass'], avatar['악기_availableTrade'], avatar['악기_attribution'], avatar['악기_statEffect(%)'], avatar['악기_매력'], avatar['악기_지성'], avatar['악기_담력'], avatar['악기_친절'], avatar['악기_availableSale'], avatar['악기_dyeable'], avatar['악기_decomposable'], avatar['이동효과_grade'], avatar['이동효과_isInner'], avatar['이동효과_isSet'], avatar['이동효과_name'], avatar['이동효과_avatarType'], avatar['이동효과_avatarType2'], avatar['이동효과_availableClass'], avatar['이동효과_availableTrade'], avatar['이동효과_attribution'], avatar['이동효과_statEffect(%)'], avatar['이동효과_매력'], avatar['이동효과_지성'], avatar['이동효과_담력'], avatar['이동효과_친절'], avatar['이동효과_availableSale'], avatar['이동효과_dyeable'], avatar['이동효과_decomposable']]       
        cursor.execute(sql, values)
        db.commit()
        db.close()
    except Exception as e:
        db.rollback()
        db.close()
        print_insert_db_exception(avatar, e)
        raise e

### 3. equipment, accessory, speical_equipment ###
def insert_equipment_accessory_sequipment_table(characterCode, data):
    result = check_code_already_in("equipment_table", characterCode)
    if result[0] == 1: return

    ## equipment keys
    equipment_parts = ['무기', '투구', '상의', '하의', '어깨', '장갑']
    accessory_parts = ['목걸이', '귀걸이1', '귀걸이2', '반지1', '반지2'] # + 팔찌, 어빌리티 스톤
    sequipment_parts = ['나침반','부적','문장']
    # 무기 장비
    aedic_keys = ['grade', 'name', 'type', 'quality', 'tier', 'itemLevel', 'ATK', 'AD(%)', 
                'setName', 'setLevel', 'REXP', 'esther', 'estherEffect','ella', 'reinforcementStep']
    # 방어구 장비
    dedic_keys = ['grade', 'name', 'type', 'quality', 'tier', 'itemLevel', 
                'SAI', 'BDEF', 'BMDEF', 'BHP', 'ADEF', 'AMDEF', 'AHP', 'AHPP',
                'setName', 'setLevel', 'REXP', 'reinforcementStep',
                'alchemyName1', 'alchemyName2', 'alchemyPoint1', 'alchemyPoint2']
    # 악세서리 장비
    adic_keys = ['grade', 'name', 'quality', 'tier', 'limitLevel', 'availableTrade', 
                'SAI', 'HP', '치명', '특화', '신속', '제압', '인내', '숙련',
                'engraving1_name', 'engraving1_point', 'engraving2_name', 'engraving2_point', 
                'dengraving_name', 'dengraving_point', 'acquirablePlace']

    # 특수장비
    sedic_keys = ['grade', 'name']

    # 장비
    equipments = {
        'characterCode': None,
    }
    # 악세서리
    accessories = {
        'characterCode': None,
        '팔찌_grade':None, '팔찌_name':None, '팔찌_tier':None, '팔찌_effect1':None, '팔찌_effect2':None,
        '팔찌_effect3':None, '팔찌_effect4':None, '팔찌_effect5':None, '팔찌_canRerollNum':None, '팔찌_canGivenNum':None,
        'AS_grade':None, 'AS_name':None, 'AS_tier':None, 'AS_HP': None, 'AS_BHP':None, 'AS_engraving1_name':None, 
        'AS_engraving1_point':None, 'AS_engraving2_name':None, 'AS_engraving2_point':None,
        'AS_dengraving_name':None, 'AS_dengraving_point':None, 'AS_setLevel' :None
    }
    # 특수 장비
    sequipments = {
        'characterCode':None, 
    }
    for part in equipment_parts:
        if part == '무기':
            for key in aedic_keys:
                equipments[f'{part}_{key}'] = None
        else:
            for key in dedic_keys:
                equipments[f'{part}_{key}'] = None
    for part in accessory_parts:
        for key in adic_keys:
            accessories[f'{part}_{key}'] = None
    for part in sequipment_parts:
        for key in sedic_keys:
            sequipments[f'{part}_{key}'] = None

    equipment = equipments.copy()
    accessory = accessories.copy()
    sequipment = sequipments.copy()
    equipment['characterCode'] = characterCode
    accessory['characterCode'] = characterCode
    sequipment['characterCode'] = characterCode

    cdf = eval(data)
    if cdf == None: return
        
    earring_count = 0
    ring_count = 0
    
    try:
        for j in range(len(cdf)):
            fd = flatten_dict(cdf[j])
            ## equipment
            if '무기' == fd['Type']:
                equipment['무기_grade'] = fd['Grade']
                if '+' in fd['Name']:
                    equipment['무기_name'] = fd['Name'].split(' ', 1)[1]
                    equipment['무기_reinforcementStep'] = fd['Name'].split(' ', 1)[0].replace('+', '')
                else:
                    equipment['무기_name'] = fd['Name']
                    equipment['무기_reinforcementStep'] = 0
                for k, v in fd.items():
                    sv = str(v)
                    sk = str(k)
                    if ('아이템 레벨' in sv) & ('티어' in sv):
                        equipment['무기_itemLevel'] = int(int_pattern.findall(sv.split(' (')[0])[0])
                        equipment['무기_tier'] = int(int_pattern.findall(sv.split(' (')[1])[0])
                    elif ('무기 공격력 +' in sv) & ('이동 속도' not in sv) :
                        equipment['무기_ATK'] = int(int_pattern.findall(sv)[0])
                    elif '추가 피해 +' in sv:
                        if '.' in sv:
                            equipment['무기_AD(%)'] = float(float_pattern.search(sv).group())
                        else:
                            equipment['무기_AD(%)'] = int(int_pattern.findall(sv)[0])
                    elif 'qualityValue' in sk:
                        equipment['무기_quality'] = v
                    elif 'Tooltip_Element_001_value_leftStr0' in sk:
                        equipment['무기_type'] = sv
                    elif ('Tooltip_Element_008_value_Element_001' in sk) & (equipment['무기_setName'] == None)\
                    & ('bPoint' not in sk) & ('contentStr' not in sk) & ('topStr' not in sk):
                        equipment['무기_setName'] = sv.split(' Lv.')[0]
                        equipment['무기_setLevel'] = int(sv.split(' Lv.')[1])
                    elif 'maximum' in sk:
                        equipment['무기_REXP'] = v
                    elif ('에스더 효과' in sv) & ('에스더 효과' != sv) &('할 수 있습니다' not in sv):
                        equipment['무기_estherEffect'] = sv.split('[')[1].replace(']', '')
                    elif '엘라 부여 완료' in sv:
                        equipment['무기_ella'] = True
                    elif sv == '에스더': # 에스더 세트 네임, 레벨 
                        equipment['무기_esther'] = True
                        equipment['무기_ella'] = False # 항상 sv==에스더가 먼저옴 -> 우선 False로 설정
                        cfd = flatten_dict(cdf[1])
                        for ck, cv in cfd.items():
                            scv = str(cv)
                            if '장갑' in scv:
                                try:
                                    set_name = scv.split(' (')[0]
                                    equipment['무기_setName'] = set_name
                                except:
                                    equipment['무기_setName'] = scv
                                try:
                                    set_level = int(int_pattern.findall(scv)[0])
                                    equipment['무기_setLevel'] = set_level
                                except:
                                    equipment['무기_setLevel'] = 1
                                break

            elif fd['Type'] in ['투구', '어깨', '상의', '하의', '장갑']:
                archemy_count = 0
                etype = fd['Type']
                equipment[f'{etype}_grade'] = fd['Grade']
                
                if '+' in fd['Name']:
                    equipment[f'{etype}_name'] = fd['Name'].split(' ', 1)[1]
                    equipment[f'{etype}_reinforcementStep'] = fd['Name'].split(' ', 1)[0].replace('+', '')
                else:
                    equipment[f'{etype}_name'] = fd['Name']
                    equipment[f'{etype}_reinforcementStep'] = 0

                for k, v in fd.items():
                    sv = str(v)
                    sk = str(k)
                    if ('아이템 레벨' in sv) & ('티어' in sv):
                        equipment[f'{etype}_itemLevel'] = int(int_pattern.findall(sv.split(' (')[0])[0])
                        equipment[f'{etype}_tier'] = int(int_pattern.findall(sv.split(' (')[1])[0])
                    elif (('[공용]' in sv) | ('(질서)' in sv) | ('(혼돈)' in sv) | \
                          ('[견갑]' in sv) | ('[상의]' in sv) | ('[하의]' in sv)):
                        archemy_count += 1
                        archemy = archemy_pattern.findall(sv)[0]
                        equipment[f'{etype}_alchemyName{archemy_count}'] = archemy[0].strip()
                        equipment[f'{etype}_alchemyPoint{archemy_count}'] = int(archemy[1])
                    elif (('힘 +' in sv) | ('민첩 +' in sv) | ('지능 +' in sv)) & ('방어력' in sv):
                        res = int_pattern.findall(sv)
                        equipment[f'{etype}_BDEF'] = int(res[0])
                        equipment[f'{etype}_BMDEF'] = int(res[1])
                        equipment[f'{etype}_SAI'] = int(res[2])
                        equipment[f'{etype}_BHP'] = int(res[3])
                    elif (('힘 +' not in sv) | ('민첩 +' not in sv) | ('지능 +' not in sv))\
                    & (('방어력' in sv) | ('생명 활성력' in sv)) & ('contentStr' not in sk):
                        res = int_pattern.findall(sv)
                        if len(res)>1:
                            equipment[f'{etype}_ADEF'] = int(res[0])
                            equipment[f'{etype}_AMDEF'] = int(res[1])
                            equipment[f'{etype}_AHP'] = int(res[2])
                        else:
                            equipment[f'{etype}_AHPP'] = int(res[0])
                    elif 'maximum' in sk:
                        equipment[f'{etype}_REXP'] = v
                    elif 'qualityValue' in sk:
                        equipment[f'{etype}_quality'] = v
                    elif 'Tooltip_Element_001_value_leftStr0' in sk:
                        equipment[f'{etype}_type'] = sv
                    elif ('Tooltip_Element_008_value_Element_001' in sk) & (equipment[f'{etype}_setName'] == None)\
                    & ('bPoint' not in sk) & ('contentStr' not in sk) & ('topStr' not in sk):
                        equipment[f'{etype}_setName'] = sv.split(' Lv.')[0]
                        equipment[f'{etype}_setLevel'] = int(sv.split(' Lv.')[1])
            
            ## accessory    
            elif fd['Type'] in ['목걸이', '귀걸이', '반지']:
                engraving_count = 0
                atype = fd['Type']
                if atype == '귀걸이': 
                    earring_count += 1
                    atype += str(earring_count)
                elif atype == '반지': 
                    ring_count += 1
                    atype += str(ring_count)
                    
                accessory[f'{atype}_grade'] = fd['Grade']
                accessory[f'{atype}_name'] = fd['Name']
                for k, v in fd.items():
                    sk = str(k)
                    sv = str(v)
                    if 'qualityValue' in sk:
                        accessory[f'{atype}_quality'] = v 
                    elif '티어' in sv:
                        accessory[f'{atype}_tier'] = int(int_pattern.findall(sv)[0])
                    elif '아이템 레벨' in sv:
                        ssv = sv.split('아이템 레벨')
                        accessory[f'{atype}_limitLevel'] = int(ssv[1])
                        try:
                            res = int_pattern.findall(ssv[0])[0]
                            accessory[f'{atype}_availableTrade'] = int(res)
                        except:
                            accessory[f'{atype}_availableTrade'] = 0
                    elif '체력' in sv:
                        res = int_pattern.findall(sv)
                        accessory[f'{atype}_SAI'] = int(res[0])
                        accessory[f'{atype}_HP'] = int(res[-1])
                    elif (('반지' not in sv) & ('귀걸이' not in sv) & ('목걸이' not in sv)) & \
                    (('치명' in sv) | ('특화' in sv) | ('신속' in sv) | ('제압' in sv) | ('인내' in sv) \
                     | ('숙련' in sv)):
                        svrs = sv.replace('+', '').split(' ')
                        for idx in range(0, len(svrs), 2):
                            accessory[f'{atype}_{svrs[idx]}'] = int(svrs[idx+1])
                    elif '활성도' in sv:
                        svrs = sv.replace('[', '').replace(']', '').replace('+', '').split(' 활성도')
                        if '감소' in svrs[0]:
                            accessory[f'{atype}_dengraving_name'] = svrs[0]
                            accessory[f'{atype}_dengraving_point'] = int(svrs[1])
                        else:
                            engraving_count += 1
                            accessory[f'{atype}_engraving{engraving_count}_name'] = svrs[0]
                            accessory[f'{atype}_engraving{engraving_count}_point'] = int(svrs[1])
                    elif ('군단장' in sv) | ('어비스' in sv) | ('카오스 던전' in sv) | ('필드 보스' in sv) |\
                    ('가디언 토벌' in sv):
                        accessory[f'{atype}_acquirablePlace'] = sv
            elif fd['Type'] =='팔찌':
                accessory['팔찌_grade'] = fd['Grade']
                accessory['팔찌_name'] = fd['Name']
                for k, v in fd.items():
                    sk = str(k)
                    sv = str(v)
                    if '티어' in sv:
                        accessory['팔찌_tier'] = int(int_pattern.findall(sv)[0])
                    elif '효과 부여' in sv:
                        try:
                            svn = int(int_pattern.findall(sv)[0])
                            accessory['팔찌_canRerollNum'] = svn
                        except:
                            accessory['팔찌_canRerollNum'] = 0
                    elif 'Tooltip_Element_004_value_Element_001' in sk:
                        effect_count = 1
                        canGivenNum = 1
                        sv= sv.replace(')', ') ')
                        while '효과 부여 가능' in sv:
                            accessory['팔찌_canGivenNum'] = canGivenNum
                            canGivenNum += 1
                            sv = sv.replace('효과 부여 가능', '', 1)
                        if canGivenNum == 1:
                            accessory['팔찌_canGivenNum'] = 0
                        for pv in plus_pattern.findall(sv):
                            pv = list(pv)
                            pv[0] = pv[0].replace('회복량', '전투 중 생명력 회복량').replace('마나', '최대 마나')\
                            .replace('공격력', '무기 공격력').replace('생명력', '최대 생명력')
                            if pv[0] == '방어력':
                                svidx = sv.find(f'{v[0]} +{v[1]}')
                                pv[0] = pv[0].replace('방어력', f'{sv[svidx-3:svidx]}방어력')
                            accessory[f'팔찌_effect{effect_count}'] = str(pv[0]) + ' +' + str(pv[1])
                            effect_count += 1
                            sv = sv.replace(f'{pv[0]} +{pv[1]}', '')
                        while len(bracelet_pattern.findall(sv)) != 0:
                            accessory[f'팔찌_effect{effect_count}'] = bracelet_pattern.findall(sv)[0][:-2].strip()
                            sv = sv.replace(bracelet_pattern.findall(sv)[0][:-2], '')
                            effect_count += 1
                        if len(sv) > 1:
                            accessory[f'팔찌_effect{effect_count}'] = sv.strip()
            elif fd['Type'] == '어빌리티 스톤':
                engraving_count = 0 
                accessory['AS_grade'] = fd['Grade']
                accessory['AS_name'] = fd['Name']
                if 'IV' in fd['Name']:
                    accessory['AS_setLevel'] = 4
                elif 'III' in fd['Name']:
                    accessory['AS_setLevel'] = 3
                elif 'II' in fd['Name']:
                    accessory['AS_setLevel'] = 2
                elif 'I' in fd['Name']:
                    accessory['AS_setLevel'] = 1
                else:
                    accessory['AS_setLevel'] = 0
                accessory['AS_BHP'] = 0
                for k, v in fd.items():
                    sv = str(v)
                    sk = str(k)
                    if ('티어' in sv) & ('[' not in sv):
                        accessory['AS_tier'] = int(sv[-1])
                    elif sk == 'Tooltip_Element_004_value_Element_001':
                        accessory['AS_HP'] = int(int_pattern.findall(sv)[0])
                    elif sk == 'Tooltip_Element_005_value_Element_001':
                        accessory['AS_BHP'] = int(int_pattern.findall(sv)[0])
                    elif '활성도' in sv:
                        svrs = sv.replace('[', '').replace(']', '').replace('+', '').split(' 활성도')
                        if '감소' in svrs[0]:
                            accessory[f'AS_dengraving_name'] = svrs[0]
                            accessory[f'AS_dengraving_point'] = int(svrs[1])
                        else:
                            engraving_count += 1
                            accessory[f'AS_engraving{engraving_count}_name'] = svrs[0]
                            accessory[f'AS_engraving{engraving_count}_point'] = int(svrs[1])
            ## special equipment
            elif fd['Type'] in ['나침반', '부적', '문장']:
                sequipment[f'{fd["Type"]}_grade'] = fd['Grade']
                sequipment[f'{fd["Type"]}_name'] = fd['Name']
                        
    except Exception as e:
        print_preprocessing_exception(fd, sk, sv, e)
        raise e
        
    ### Insert DB ###
    # equipment table
    db, cursor = get_db_cursor()
    try:  
        sql = f"""
            INSERT INTO lostark.equipment_table (
                {''.join(f'{key}, ' for key in equipments.keys())[:-2]})
            VALUES ({''.join('%s, ' for _ in range(len(equipments.keys())))[:-2]});
            """.replace('무기_AD(%)', '`무기_AD(%%)`')
        values = [equipment['characterCode'], equipment['무기_grade'], equipment['무기_name'], equipment['무기_type'], equipment['무기_quality'], equipment['무기_tier'], equipment['무기_itemLevel'], equipment['무기_ATK'], equipment['무기_AD(%)'], equipment['무기_setName'], equipment['무기_setLevel'], equipment['무기_REXP'], equipment['무기_esther'], equipment['무기_estherEffect'], equipment['무기_ella'], equipment['무기_reinforcementStep'], equipment['투구_grade'], equipment['투구_name'], equipment['투구_type'], equipment['투구_quality'], equipment['투구_tier'], equipment['투구_itemLevel'], equipment['투구_SAI'], equipment['투구_BDEF'], equipment['투구_BMDEF'], equipment['투구_BHP'], equipment['투구_ADEF'], equipment['투구_AMDEF'], equipment['투구_AHP'], equipment['투구_AHPP'], equipment['투구_setName'], equipment['투구_setLevel'], equipment['투구_REXP'], equipment['투구_reinforcementStep'], equipment['투구_alchemyName1'], equipment['투구_alchemyName2'], equipment['투구_alchemyPoint1'], equipment['투구_alchemyPoint2'], equipment['상의_grade'], equipment['상의_name'], equipment['상의_type'], equipment['상의_quality'], equipment['상의_tier'], equipment['상의_itemLevel'], equipment['상의_SAI'], equipment['상의_BDEF'], equipment['상의_BMDEF'], equipment['상의_BHP'], equipment['상의_ADEF'], equipment['상의_AMDEF'], equipment['상의_AHP'], equipment['상의_AHPP'], equipment['상의_setName'], equipment['상의_setLevel'], equipment['상의_REXP'], equipment['상의_reinforcementStep'], equipment['상의_alchemyName1'], equipment['상의_alchemyName2'], equipment['상의_alchemyPoint1'], equipment['상의_alchemyPoint2'], equipment['하의_grade'], equipment['하의_name'], equipment['하의_type'], equipment['하의_quality'], equipment['하의_tier'], equipment['하의_itemLevel'], equipment['하의_SAI'], equipment['하의_BDEF'], equipment['하의_BMDEF'], equipment['하의_BHP'], equipment['하의_ADEF'], equipment['하의_AMDEF'], equipment['하의_AHP'], equipment['하의_AHPP'], equipment['하의_setName'], equipment['하의_setLevel'], equipment['하의_REXP'], equipment['하의_reinforcementStep'], equipment['하의_alchemyName1'], equipment['하의_alchemyName2'], equipment['하의_alchemyPoint1'], equipment['하의_alchemyPoint2'], equipment['어깨_grade'], equipment['어깨_name'], equipment['어깨_type'], equipment['어깨_quality'], equipment['어깨_tier'], equipment['어깨_itemLevel'], equipment['어깨_SAI'], equipment['어깨_BDEF'], equipment['어깨_BMDEF'], equipment['어깨_BHP'], equipment['어깨_ADEF'], equipment['어깨_AMDEF'], equipment['어깨_AHP'], equipment['어깨_AHPP'], equipment['어깨_setName'], equipment['어깨_setLevel'], equipment['어깨_REXP'], equipment['어깨_reinforcementStep'], equipment['어깨_alchemyName1'], equipment['어깨_alchemyName2'], equipment['어깨_alchemyPoint1'], equipment['어깨_alchemyPoint2'], equipment['장갑_grade'], equipment['장갑_name'], equipment['장갑_type'], equipment['장갑_quality'], equipment['장갑_tier'], equipment['장갑_itemLevel'], equipment['장갑_SAI'], equipment['장갑_BDEF'], equipment['장갑_BMDEF'], equipment['장갑_BHP'], equipment['장갑_ADEF'], equipment['장갑_AMDEF'], equipment['장갑_AHP'], equipment['장갑_AHPP'], equipment['장갑_setName'], equipment['장갑_setLevel'], equipment['장갑_REXP'], equipment['장갑_reinforcementStep'], equipment['장갑_alchemyName1'], equipment['장갑_alchemyName2'], equipment['장갑_alchemyPoint1'], equipment['장갑_alchemyPoint2']]
        cursor.execute(sql, values)
        db.commit()
    except Exception as e:
        db.rollback()
        db.close()
        print_insert_db_exception(equipment, e)
        raise e
        
    # accessory table    
    try:  
        sql = f"""
            INSERT INTO lostark.accessory_table (
                {''.join(f'`{key}`, ' for key in accessories.keys())[:-2]})
            VALUES ({''.join('%s, ' for _ in range(len(accessories.keys())))[:-2]});
            """
        values = [accessory['characterCode'], accessory['팔찌_grade'], accessory['팔찌_name'], accessory['팔찌_tier'], accessory['팔찌_effect1'], accessory['팔찌_effect2'], accessory['팔찌_effect3'], accessory['팔찌_effect4'], accessory['팔찌_effect5'], accessory['팔찌_canRerollNum'], accessory['팔찌_canGivenNum'], accessory['AS_grade'], accessory['AS_name'], accessory['AS_tier'], accessory['AS_HP'], accessory['AS_BHP'], accessory['AS_engraving1_name'], accessory['AS_engraving1_point'], accessory['AS_engraving2_name'], accessory['AS_engraving2_point'], accessory['AS_dengraving_name'], accessory['AS_dengraving_point'], accessory['AS_setLevel'], accessory['목걸이_grade'], accessory['목걸이_name'], accessory['목걸이_quality'], accessory['목걸이_tier'], accessory['목걸이_limitLevel'], accessory['목걸이_availableTrade'], accessory['목걸이_SAI'], accessory['목걸이_HP'], accessory['목걸이_치명'], accessory['목걸이_특화'], accessory['목걸이_신속'], accessory['목걸이_제압'], accessory['목걸이_인내'], accessory['목걸이_숙련'], accessory['목걸이_engraving1_name'], accessory['목걸이_engraving1_point'], accessory['목걸이_engraving2_name'], accessory['목걸이_engraving2_point'], accessory['목걸이_dengraving_name'], accessory['목걸이_dengraving_point'], accessory['목걸이_acquirablePlace'], accessory['귀걸이1_grade'], accessory['귀걸이1_name'], accessory['귀걸이1_quality'], accessory['귀걸이1_tier'], accessory['귀걸이1_limitLevel'], accessory['귀걸이1_availableTrade'], accessory['귀걸이1_SAI'], accessory['귀걸이1_HP'], accessory['귀걸이1_치명'], accessory['귀걸이1_특화'], accessory['귀걸이1_신속'], accessory['귀걸이1_제압'], accessory['귀걸이1_인내'], accessory['귀걸이1_숙련'], accessory['귀걸이1_engraving1_name'], accessory['귀걸이1_engraving1_point'], accessory['귀걸이1_engraving2_name'], accessory['귀걸이1_engraving2_point'], accessory['귀걸이1_dengraving_name'], accessory['귀걸이1_dengraving_point'], accessory['귀걸이1_acquirablePlace'], accessory['귀걸이2_grade'], accessory['귀걸이2_name'], accessory['귀걸이2_quality'], accessory['귀걸이2_tier'], accessory['귀걸이2_limitLevel'], accessory['귀걸이2_availableTrade'], accessory['귀걸이2_SAI'], accessory['귀걸이2_HP'], accessory['귀걸이2_치명'], accessory['귀걸이2_특화'], accessory['귀걸이2_신속'], accessory['귀걸이2_제압'], accessory['귀걸이2_인내'], accessory['귀걸이2_숙련'], accessory['귀걸이2_engraving1_name'], accessory['귀걸이2_engraving1_point'], accessory['귀걸이2_engraving2_name'], accessory['귀걸이2_engraving2_point'], accessory['귀걸이2_dengraving_name'], accessory['귀걸이2_dengraving_point'], accessory['귀걸이2_acquirablePlace'], accessory['반지1_grade'], accessory['반지1_name'], accessory['반지1_quality'], accessory['반지1_tier'], accessory['반지1_limitLevel'], accessory['반지1_availableTrade'], accessory['반지1_SAI'], accessory['반지1_HP'], accessory['반지1_치명'], accessory['반지1_특화'], accessory['반지1_신속'], accessory['반지1_제압'], accessory['반지1_인내'], accessory['반지1_숙련'], accessory['반지1_engraving1_name'], accessory['반지1_engraving1_point'], accessory['반지1_engraving2_name'], accessory['반지1_engraving2_point'], accessory['반지1_dengraving_name'], accessory['반지1_dengraving_point'], accessory['반지1_acquirablePlace'], accessory['반지2_grade'], accessory['반지2_name'], accessory['반지2_quality'], accessory['반지2_tier'], accessory['반지2_limitLevel'], accessory['반지2_availableTrade'], accessory['반지2_SAI'], accessory['반지2_HP'], accessory['반지2_치명'], accessory['반지2_특화'], accessory['반지2_신속'], accessory['반지2_제압'], accessory['반지2_인내'], accessory['반지2_숙련'], accessory['반지2_engraving1_name'], accessory['반지2_engraving1_point'], accessory['반지2_engraving2_name'], accessory['반지2_engraving2_point'], accessory['반지2_dengraving_name'], accessory['반지2_dengraving_point'], accessory['반지2_acquirablePlace']]
        cursor.execute(sql, values)
        db.commit()
    except Exception as e:
        db.rollback()
        db.close()
        print_insert_db_exception(accessory, e)
        raise e
        
    # special equipment table
    try: 
        sql = f"""
            INSERT INTO lostark.special_equipment_table (
                {''.join(f'`{key}`, ' for key in sequipments.keys())[:-2]})
            VALUES ({''.join('%s, ' for _ in range(len(sequipments.keys())))[:-2]});
            """
        values = [sequipment['characterCode'], sequipment['나침반_grade'], sequipment['나침반_name'], sequipment['부적_grade'], sequipment['부적_name'], sequipment['문장_grade'], sequipment['문장_name']]
        cursor.execute(sql, values)
        db.commit()
        db.close()
    except Exception as e:
        db.rollback()
        db.close()
        print_insert_db_exception(sequipment, e)
        raise e

### 4. skill ###
def insert_skill_table(characterCode, data):
    result = check_code_already_in("skill_table", characterCode)
    if result[0] == 1: return
    cdf = eval(data)
    if cdf==None: return

    ## skill keys
    skill_parts = [f'skill{i}' for i in range(1,17)] # 16개 스킬만 고려
    dic_keys = ['name', 'level', 'cooltime','tripod1_name', 'tripod1_point', 'tripod2_name', 'tripod2_point',
                'tripod3_name', 'tripod3_point', 'runeName', 'runeGrade','headAttack', 'backAttack', 
                'partBreak', 'stagger', 'counter', '마나', '배터리', '버블', '충격', '기력', '내공', '영혼석',
                '경직면역', '피격면역', '상태이상면역']
    skills = {
        'characterCode': None,
    }
    for part in skill_parts:
        for key in dic_keys:
            skills[f'{part}_{key}'] = None
        
    skill = skills.copy()
    skill['characterCode'] = characterCode
        
    skill_count = 0
    try:
        for j in range(len(cdf)):
            fd = flatten_dict(cdf[j])
            try: 
                # 룬을 끼고 있지 않다면
                _ = fd['Rune']
                exist_rune = False
            except: 
                exist_rune=True

            # 스킬레벨 1 이상이거나 룬을 착용했다면 사용하는 스킬로 간주
            if (fd['Level'] > 1) or (exist_rune == True): 
                skill_count += 1
                tripod_count = 0
                skill[f'skill{skill_count}_level'] = fd['Level']
                skill[f'skill{skill_count}_name'] = fd['Name']
                if exist_rune == True:
                    skill[f'skill{skill_count}_runeName'] = fd['Rune_Name']
                    skill[f'skill{skill_count}_runeGrade'] = fd['Rune_Grade']
                for k, v in fd.items():
                    sv = str(v)
                    sk = str(k)
                    if ('_value_leftText' in sk) & ('재사용 대기시간' in sv):
                        skill[f'skill{skill_count}_cooltime'] = int(int_pattern.findall(sv)[0])
                    elif ('Tooltip_Element_' in sk) & ('desc' not in sk) & ('소모' in sv) &\
                    ('않는다' not in sv) & ('증가' not in sv) & ('감소' not in sv) & ('회복' not in sv):
                        sv = sv.replace('|', '')
                        sv = sv.split(', ')
                        resourceName = resource_pattern.findall(sv[0])[0]
                        if len(sv) > 1:
                            resourceName2 = resource_pattern.findall(sv[1])[0]
                            if '모두 소모' in sv[0]: # 인파이터
                                skill[f'skill{skill_count}_{resourceName}'] = -100
                            elif resourceName in ['기력', '충격']: # 인파이터
                                skill[f'skill{skill_count}_{resourceName}'] = -1 * int(int_pattern.findall(sv[0])[0])
                                skill[f'skill{skill_count}_{resourceName2}'] = int(int_pattern.findall(sv[1])[0])
                            else: # 소울이터, 스트라이커
                                skill[f'skill{skill_count}_{resourceName}'] = -1 * int(int_pattern.findall(sv[0])[0])
                                skill[f'skill{skill_count}_{resourceName2}'] = -1 * int(int_pattern.findall(sv[1])[0])
                        else: # 그 외 직업
                            skill[f'skill{skill_count}_{resourceName}'] = -1 * int(int_pattern.findall(sv[0])[0])
                    elif ('_value_Element_' in sk) & ('name' in sk) & (sv != ''):
                        tripod_count+=1
                        skill[f'skill{skill_count}_tripod{tripod_count}_name'] = sv
                    elif ('_value_Element_' in sk) & ('tier' in sk) & (sv != ''):
                        skill[f'skill{skill_count}_tripod{tripod_count}_point'] = int(int_pattern.findall(sv)[0])
                    elif ('공격 타입 :' in sv) | ('부위 파괴 :' in sv) | ('무력화 :' in sv) | ('슈퍼아머 :' in sv) |\
                    ('카운터 :' in sv):
                        if ('공격 타입 :' in sv) :
                            skill[f'skill{skill_count}_headAttack'] = '헤드 어택' in sv
                            skill[f'skill{skill_count}_backAttack'] = '백 어택' in sv
                        if ('부위 파괴 :' in sv) :
                            start_idx = sv.find('부위 파괴 : 레벨') + len('부위 파괴 : 레벨')
                            # 띄어쓰기가 제대로 되지않는 경우가 있어 replace
                            number = sv[start_idx:].split()[0].replace('무력화', '').replace('공격', '')\
                            .replace('슈퍼아머', '')
                            skill[f'skill{skill_count}_partBreak'] = int(number)
                        else:
                            skill[f'skill{skill_count}_partBreak'] = 0
                        if ('무력화 :' in sv) :
                            start_idx = sv.find('무력화 : ') + len('무력화 : ')
                            stagger = sv[start_idx:].split()[0].replace('공격', '').replace('카운터', '')\
                            .replace('슈퍼아머', '')
                            skill[f'skill{skill_count}_stagger'] = stagger
                        else: 
                            skill[f'skill{skill_count}_stagger'] = 0
                        skill[f'skill{skill_count}_counter'] = '카운터' in sv
                        skill[f'skill{skill_count}_경직면역'] = '경직 면역' in sv
                        skill[f'skill{skill_count}_피격면역'] = '피격이상 면역' in sv
                        skill[f'skill{skill_count}_상태이상면역'] = '상태이상 면역' in sv
    except Exception as e:
        print_preprocessing_exception(fd, sk, sv, e)
        raise e

    try:  
        db, cursor = get_db_cursor()
        sql = f"""
            INSERT INTO lostark.skill_table (
                {''.join(f'{key}, ' for key in skills.keys())[:-2]})
            VALUES ({''.join('%s, ' for _ in range(len(skills.keys())))[:-2]});
            """
        values = [skill['characterCode'], skill['skill1_name'], skill['skill1_level'], skill['skill1_cooltime'], skill['skill1_tripod1_name'], skill['skill1_tripod1_point'], skill['skill1_tripod2_name'], skill['skill1_tripod2_point'], skill['skill1_tripod3_name'], skill['skill1_tripod3_point'], skill['skill1_runeName'], skill['skill1_runeGrade'], skill['skill1_headAttack'], skill['skill1_backAttack'], skill['skill1_partBreak'], skill['skill1_stagger'], skill['skill1_counter'], skill['skill1_마나'], skill['skill1_배터리'], skill['skill1_버블'], skill['skill1_충격'], skill['skill1_기력'], skill['skill1_내공'], skill['skill1_영혼석'], skill['skill1_경직면역'], skill['skill1_피격면역'], skill['skill1_상태이상면역'], skill['skill2_name'], skill['skill2_level'], skill['skill2_cooltime'], skill['skill2_tripod1_name'], skill['skill2_tripod1_point'], skill['skill2_tripod2_name'], skill['skill2_tripod2_point'], skill['skill2_tripod3_name'], skill['skill2_tripod3_point'], skill['skill2_runeName'], skill['skill2_runeGrade'], skill['skill2_headAttack'], skill['skill2_backAttack'], skill['skill2_partBreak'], skill['skill2_stagger'], skill['skill2_counter'], skill['skill2_마나'], skill['skill2_배터리'], skill['skill2_버블'], skill['skill2_충격'], skill['skill2_기력'], skill['skill2_내공'], skill['skill2_영혼석'], skill['skill2_경직면역'], skill['skill2_피격면역'], skill['skill2_상태이상면역'], skill['skill3_name'], skill['skill3_level'], skill['skill3_cooltime'], skill['skill3_tripod1_name'], skill['skill3_tripod1_point'], skill['skill3_tripod2_name'], skill['skill3_tripod2_point'], skill['skill3_tripod3_name'], skill['skill3_tripod3_point'], skill['skill3_runeName'], skill['skill3_runeGrade'], skill['skill3_headAttack'], skill['skill3_backAttack'], skill['skill3_partBreak'], skill['skill3_stagger'], skill['skill3_counter'], skill['skill3_마나'], skill['skill3_배터리'], skill['skill3_버블'], skill['skill3_충격'], skill['skill3_기력'], skill['skill3_내공'], skill['skill3_영혼석'], skill['skill3_경직면역'], skill['skill3_피격면역'], skill['skill3_상태이상면역'], skill['skill4_name'], skill['skill4_level'], skill['skill4_cooltime'], skill['skill4_tripod1_name'], skill['skill4_tripod1_point'], skill['skill4_tripod2_name'], skill['skill4_tripod2_point'], skill['skill4_tripod3_name'], skill['skill4_tripod3_point'], skill['skill4_runeName'], skill['skill4_runeGrade'], skill['skill4_headAttack'], skill['skill4_backAttack'], skill['skill4_partBreak'], skill['skill4_stagger'], skill['skill4_counter'], skill['skill4_마나'], skill['skill4_배터리'], skill['skill4_버블'], skill['skill4_충격'], skill['skill4_기력'], skill['skill4_내공'], skill['skill4_영혼석'], skill['skill4_경직면역'], skill['skill4_피격면역'], skill['skill4_상태이상면역'], skill['skill5_name'], skill['skill5_level'], skill['skill5_cooltime'], skill['skill5_tripod1_name'], skill['skill5_tripod1_point'], skill['skill5_tripod2_name'], skill['skill5_tripod2_point'], skill['skill5_tripod3_name'], skill['skill5_tripod3_point'], skill['skill5_runeName'], skill['skill5_runeGrade'], skill['skill5_headAttack'], skill['skill5_backAttack'], skill['skill5_partBreak'], skill['skill5_stagger'], skill['skill5_counter'], skill['skill5_마나'], skill['skill5_배터리'], skill['skill5_버블'], skill['skill5_충격'], skill['skill5_기력'], skill['skill5_내공'], skill['skill5_영혼석'], skill['skill5_경직면역'], skill['skill5_피격면역'], skill['skill5_상태이상면역'], skill['skill6_name'], skill['skill6_level'], skill['skill6_cooltime'], skill['skill6_tripod1_name'], skill['skill6_tripod1_point'], skill['skill6_tripod2_name'], skill['skill6_tripod2_point'], skill['skill6_tripod3_name'], skill['skill6_tripod3_point'], skill['skill6_runeName'], skill['skill6_runeGrade'], skill['skill6_headAttack'], skill['skill6_backAttack'], skill['skill6_partBreak'], skill['skill6_stagger'], skill['skill6_counter'], skill['skill6_마나'], skill['skill6_배터리'], skill['skill6_버블'], skill['skill6_충격'], skill['skill6_기력'], skill['skill6_내공'], skill['skill6_영혼석'], skill['skill6_경직면역'], skill['skill6_피격면역'], skill['skill6_상태이상면역'], skill['skill7_name'], skill['skill7_level'], skill['skill7_cooltime'], skill['skill7_tripod1_name'], skill['skill7_tripod1_point'], skill['skill7_tripod2_name'], skill['skill7_tripod2_point'], skill['skill7_tripod3_name'], skill['skill7_tripod3_point'], skill['skill7_runeName'], skill['skill7_runeGrade'], skill['skill7_headAttack'], skill['skill7_backAttack'], skill['skill7_partBreak'], skill['skill7_stagger'], skill['skill7_counter'], skill['skill7_마나'], skill['skill7_배터리'], skill['skill7_버블'], skill['skill7_충격'], skill['skill7_기력'], skill['skill7_내공'], skill['skill7_영혼석'], skill['skill7_경직면역'], skill['skill7_피격면역'], skill['skill7_상태이상면역'], skill['skill8_name'], skill['skill8_level'], skill['skill8_cooltime'], skill['skill8_tripod1_name'], skill['skill8_tripod1_point'], skill['skill8_tripod2_name'], skill['skill8_tripod2_point'], skill['skill8_tripod3_name'], skill['skill8_tripod3_point'], skill['skill8_runeName'], skill['skill8_runeGrade'], skill['skill8_headAttack'], skill['skill8_backAttack'], skill['skill8_partBreak'], skill['skill8_stagger'], skill['skill8_counter'], skill['skill8_마나'], skill['skill8_배터리'], skill['skill8_버블'], skill['skill8_충격'], skill['skill8_기력'], skill['skill8_내공'], skill['skill8_영혼석'], skill['skill8_경직면역'], skill['skill8_피격면역'], skill['skill8_상태이상면역'], skill['skill9_name'], skill['skill9_level'], skill['skill9_cooltime'], skill['skill9_tripod1_name'], skill['skill9_tripod1_point'], skill['skill9_tripod2_name'], skill['skill9_tripod2_point'], skill['skill9_tripod3_name'], skill['skill9_tripod3_point'], skill['skill9_runeName'], skill['skill9_runeGrade'], skill['skill9_headAttack'], skill['skill9_backAttack'], skill['skill9_partBreak'], skill['skill9_stagger'], skill['skill9_counter'], skill['skill9_마나'], skill['skill9_배터리'], skill['skill9_버블'], skill['skill9_충격'], skill['skill9_기력'], skill['skill9_내공'], skill['skill9_영혼석'], skill['skill9_경직면역'], skill['skill9_피격면역'], skill['skill9_상태이상면역'], skill['skill10_name'], skill['skill10_level'], skill['skill10_cooltime'], skill['skill10_tripod1_name'], skill['skill10_tripod1_point'], skill['skill10_tripod2_name'], skill['skill10_tripod2_point'], skill['skill10_tripod3_name'], skill['skill10_tripod3_point'], skill['skill10_runeName'], skill['skill10_runeGrade'], skill['skill10_headAttack'], skill['skill10_backAttack'], skill['skill10_partBreak'], skill['skill10_stagger'], skill['skill10_counter'], skill['skill10_마나'], skill['skill10_배터리'], skill['skill10_버블'], skill['skill10_충격'], skill['skill10_기력'], skill['skill10_내공'], skill['skill10_영혼석'], skill['skill10_경직면역'], skill['skill10_피격면역'], skill['skill10_상태이상면역'], skill['skill11_name'], skill['skill11_level'], skill['skill11_cooltime'], skill['skill11_tripod1_name'], skill['skill11_tripod1_point'], skill['skill11_tripod2_name'], skill['skill11_tripod2_point'], skill['skill11_tripod3_name'], skill['skill11_tripod3_point'], skill['skill11_runeName'], skill['skill11_runeGrade'], skill['skill11_headAttack'], skill['skill11_backAttack'], skill['skill11_partBreak'], skill['skill11_stagger'], skill['skill11_counter'], skill['skill11_마나'], skill['skill11_배터리'], skill['skill11_버블'], skill['skill11_충격'], skill['skill11_기력'], skill['skill11_내공'], skill['skill11_영혼석'], skill['skill11_경직면역'], skill['skill11_피격면역'], skill['skill11_상태이상면역'], skill['skill12_name'], skill['skill12_level'], skill['skill12_cooltime'], skill['skill12_tripod1_name'], skill['skill12_tripod1_point'], skill['skill12_tripod2_name'], skill['skill12_tripod2_point'], skill['skill12_tripod3_name'], skill['skill12_tripod3_point'], skill['skill12_runeName'], skill['skill12_runeGrade'], skill['skill12_headAttack'], skill['skill12_backAttack'], skill['skill12_partBreak'], skill['skill12_stagger'], skill['skill12_counter'], skill['skill12_마나'], skill['skill12_배터리'], skill['skill12_버블'], skill['skill12_충격'], skill['skill12_기력'], skill['skill12_내공'], skill['skill12_영혼석'], skill['skill12_경직면역'], skill['skill12_피격면역'], skill['skill12_상태이상면역'], skill['skill13_name'], skill['skill13_level'], skill['skill13_cooltime'], skill['skill13_tripod1_name'], skill['skill13_tripod1_point'], skill['skill13_tripod2_name'], skill['skill13_tripod2_point'], skill['skill13_tripod3_name'], skill['skill13_tripod3_point'], skill['skill13_runeName'], skill['skill13_runeGrade'], skill['skill13_headAttack'], skill['skill13_backAttack'], skill['skill13_partBreak'], skill['skill13_stagger'], skill['skill13_counter'], skill['skill13_마나'], skill['skill13_배터리'], skill['skill13_버블'], skill['skill13_충격'], skill['skill13_기력'], skill['skill13_내공'], skill['skill13_영혼석'], skill['skill13_경직면역'], skill['skill13_피격면역'], skill['skill13_상태이상면역'], skill['skill14_name'], skill['skill14_level'], skill['skill14_cooltime'], skill['skill14_tripod1_name'], skill['skill14_tripod1_point'], skill['skill14_tripod2_name'], skill['skill14_tripod2_point'], skill['skill14_tripod3_name'], skill['skill14_tripod3_point'], skill['skill14_runeName'], skill['skill14_runeGrade'], skill['skill14_headAttack'], skill['skill14_backAttack'], skill['skill14_partBreak'], skill['skill14_stagger'], skill['skill14_counter'], skill['skill14_마나'], skill['skill14_배터리'], skill['skill14_버블'], skill['skill14_충격'], skill['skill14_기력'], skill['skill14_내공'], skill['skill14_영혼석'], skill['skill14_경직면역'], skill['skill14_피격면역'], skill['skill14_상태이상면역'], skill['skill15_name'], skill['skill15_level'], skill['skill15_cooltime'], skill['skill15_tripod1_name'], skill['skill15_tripod1_point'], skill['skill15_tripod2_name'], skill['skill15_tripod2_point'], skill['skill15_tripod3_name'], skill['skill15_tripod3_point'], skill['skill15_runeName'], skill['skill15_runeGrade'], skill['skill15_headAttack'], skill['skill15_backAttack'], skill['skill15_partBreak'], skill['skill15_stagger'], skill['skill15_counter'], skill['skill15_마나'], skill['skill15_배터리'], skill['skill15_버블'], skill['skill15_충격'], skill['skill15_기력'], skill['skill15_내공'], skill['skill15_영혼석'], skill['skill15_경직면역'], skill['skill15_피격면역'], skill['skill15_상태이상면역'], skill['skill16_name'], skill['skill16_level'], skill['skill16_cooltime'], skill['skill16_tripod1_name'], skill['skill16_tripod1_point'], skill['skill16_tripod2_name'], skill['skill16_tripod2_point'], skill['skill16_tripod3_name'], skill['skill16_tripod3_point'], skill['skill16_runeName'], skill['skill16_runeGrade'], skill['skill16_headAttack'], skill['skill16_backAttack'], skill['skill16_partBreak'], skill['skill16_stagger'], skill['skill16_counter'], skill['skill16_마나'], skill['skill16_배터리'], skill['skill16_버블'], skill['skill16_충격'], skill['skill16_기력'], skill['skill16_내공'], skill['skill16_영혼석'], skill['skill16_경직면역'], skill['skill16_피격면역'], skill['skill16_상태이상면역']] 
        cursor.execute(sql, values)
        db.commit()
        db.close()
    except Exception as e:
        db.rollback()
        db.close()
        print_insert_db_exception(skill, e)
        raise e

### 5. gem ###
def insert_gem_table(characterCode, data):
    result = check_code_already_in("gem_table", characterCode)
    if result[0] == 1: return

    ## gem keys
    gem_parts = [f'gem{i}' for i in range(1, 12)] # 11개의 보석
    dic_keys = ['type', 'level', 'grade','skillName', 'tier', 'availableTrade']
    gems = {
        'characterCode': None,
    }
    for part in gem_parts:
        for key in dic_keys:
            gems[f'{part}_{key}'] = None

    gem = gems.copy()
    gem['characterCode'] = characterCode
    cdf = eval(data)
    if cdf==None: return
    cdf = cdf['Gems']
    gem_count = 0
    try:
        for j in range(len(cdf)):
            gem_count += 1
            fd = flatten_dict(cdf[j])
            gem[f'gem{gem_count}_grade'] = fd['Grade']
            gem[f'gem{gem_count}_level'] = fd['Level']
            for k, v in fd.items():
                sk = str(k)
                sv = str(v)
                if '홍염' in sv:
                    gem[f'gem{gem_count}_type'] = '홍염'
                elif '멸화' in sv:
                    gem[f'gem{gem_count}_type'] = '멸화'
                elif '티어' in sv:
                    gem[f'gem{gem_count}_tier'] = int(int_pattern.findall(sv)[0])
                elif '재사용' in sv:
                    gem[f'gem{gem_count}_skillName'] =  sv.split('재사용')[0]
                elif '피해' in sv:
                    gem[f'gem{gem_count}_skillName'] =  sv.split('피해')[0]
                elif '거래' in sv:
                    gem[f'gem{gem_count}_availableTrade'] = '가능' in sv   
    except Exception as e:
        print_preprocessing_exception(fd, sk, sv, e)
        raise e
        
    try:
        db, cursor = get_db_cursor()
        sql = f"""
            INSERT INTO lostark.gem_table (
                {''.join(f'{key}, ' for key in gems.keys())[:-2]})
            VALUES ({''.join('%s, ' for _ in range(len(gems.keys())))[:-2]});
            """
        values = [gem['characterCode'], gem['gem1_type'], gem['gem1_level'], gem['gem1_grade'], gem['gem1_skillName'], gem['gem1_tier'], gem['gem1_availableTrade'], gem['gem2_type'], gem['gem2_level'], gem['gem2_grade'], gem['gem2_skillName'], gem['gem2_tier'], gem['gem2_availableTrade'], gem['gem3_type'], gem['gem3_level'], gem['gem3_grade'], gem['gem3_skillName'], gem['gem3_tier'], gem['gem3_availableTrade'], gem['gem4_type'], gem['gem4_level'], gem['gem4_grade'], gem['gem4_skillName'], gem['gem4_tier'], gem['gem4_availableTrade'], gem['gem5_type'], gem['gem5_level'], gem['gem5_grade'], gem['gem5_skillName'], gem['gem5_tier'], gem['gem5_availableTrade'], gem['gem6_type'], gem['gem6_level'], gem['gem6_grade'], gem['gem6_skillName'], gem['gem6_tier'], gem['gem6_availableTrade'], gem['gem7_type'], gem['gem7_level'], gem['gem7_grade'], gem['gem7_skillName'], gem['gem7_tier'], gem['gem7_availableTrade'], gem['gem8_type'], gem['gem8_level'], gem['gem8_grade'], gem['gem8_skillName'], gem['gem8_tier'], gem['gem8_availableTrade'], gem['gem9_type'], gem['gem9_level'], gem['gem9_grade'], gem['gem9_skillName'], gem['gem9_tier'], gem['gem9_availableTrade'], gem['gem10_type'], gem['gem10_level'], gem['gem10_grade'], gem['gem10_skillName'], gem['gem10_tier'], gem['gem10_availableTrade'], gem['gem11_type'], gem['gem11_level'], gem['gem11_grade'], gem['gem11_skillName'], gem['gem11_tier'], gem['gem11_availableTrade']]
        cursor.execute(sql, values)
        db.commit()
        db.close()
    except Exception as e:
        db.rollback()
        db.close()
        print_insert_db_exception(gem, e)
        raise e

### 6. engraving ###
def insert_engraving_table(characterCode, data):
    result = check_code_already_in("engraving_table", characterCode)
    if result[0] == 1: return

    ## engraving keys
    engraving_parts = [f'engraving{i}' for i in range(1, 16)] # 15개의 각인만 고려
    dic_keys = ['name', 'level']
    engravings = {
        'characterCode': None,
        'grantName1': None,'grantPoint1':None, 'grantName2':None, 'grantPoint2':None
    }
    for part in engraving_parts:
        for key in dic_keys:
            engravings[f'{part}_{key}'] = None

    engraving = engravings.copy()
    engraving['characterCode'] = characterCode
    cdf = eval(data)
    if cdf==None: return
        
    engraving_count = 0
    grant_count = 0
    try:
        cdfef = cdf['Effects'] # 활성화 각인
        if cdfef==None:
            pass
        else:
            for j in range(len(cdfef)):
                engraving_count += 1
                fd = flatten_dict(cdfef[j])
                engraving[f'engraving{engraving_count}_name'] = fd['Name'].split(' Lv. ')[0]
                engraving[f'engraving{engraving_count}_level'] = fd['Name'].split(' Lv. ')[-1]
            
        cdfen = cdf['Engravings']
        if cdfen==None: return
        for j in range(len(cdfen)):
            grant_count += 1
            fd = flatten_dict(cdfen[j])
            engraving[f'grantName{grant_count}'] = fd['Name']
            for k, v in fd.items():
                sk = str(k)
                sv = str(v)
                if '각인 활성' in sv:
                    engraving[f'grantPoint{grant_count}'] = int(int_pattern.findall(sv)[0])

    except Exception as e:
        print_preprocessing_exception(fd, sk, sv, e)
        raise e
        
    try:  
        db, cursor = get_db_cursor()
        sql = f"""
            INSERT INTO lostark.engraving_table (
                {''.join(f'{key}, ' for key in engravings.keys())[:-2]})
            VALUES ({''.join('%s, ' for _ in range(len(engravings.keys())))[:-2]});
            """
        values = [engraving['characterCode'], engraving['grantName1'], engraving['grantPoint1'], engraving['grantName2'], engraving['grantPoint2'], engraving['engraving1_name'], engraving['engraving1_level'], engraving['engraving2_name'], engraving['engraving2_level'], engraving['engraving3_name'], engraving['engraving3_level'], engraving['engraving4_name'], engraving['engraving4_level'], engraving['engraving5_name'], engraving['engraving5_level'], engraving['engraving6_name'], engraving['engraving6_level'], engraving['engraving7_name'], engraving['engraving7_level'], engraving['engraving8_name'], engraving['engraving8_level'], engraving['engraving9_name'], engraving['engraving9_level'], engraving['engraving10_name'], engraving['engraving10_level'], engraving['engraving11_name'], engraving['engraving11_level'], engraving['engraving12_name'], engraving['engraving12_level'], engraving['engraving13_name'], engraving['engraving13_level'], engraving['engraving14_name'], engraving['engraving14_level'], engraving['engraving15_name'], engraving['engraving15_level']]
        cursor.execute(sql, values)
        db.commit()
        db.close()
    except Exception as e:
        db.rollback()
        db.close()
        print_insert_db_exception(engraving, e)
        raise e

### 7. card ###
def insert_card_table(characterCode, data):
    result = check_code_already_in("card_table", characterCode)
    if result[0] == 1: return

    ## card keys
    card_parts = [f'card{i}' for i in range(1, 7)] # 카드 6장
    dic_keys = ['name', 'level']
    cards = {
        'characterCode': None,
    }
    for part in card_parts:
        for key in dic_keys:
            cards[f'{part}_{key}'] = None
    for i in range(1, 6): # 세트 5개
        cards[f'setName{i}'] = None
        cards[f'setPoint{i}'] = None
        
    card = cards.copy()
    card['characterCode'] = characterCode
    cdf = eval(data)
    if cdf==None: return
    card_count = 0
    set_count = 0
    try:
        cdfc = cdf['Cards'] # 장착 카드
        if cdfc == None: return
        for j in range(len(cdfc)):
            card_count += 1
            fd = flatten_dict(cdfc[j])
            card[f'card{card_count}_name'] = fd['Name']
            card[f'card{card_count}_level'] = fd['AwakeCount']

        cdfe = cdf['Effects'] # 활성화된 세트
        if cdfe==None: return
        for j in range(len(cdfe)):
            try:
                set_name = cdfe[j]['Items'][-1]['Name'].split(' (')
            except:
                continue
            set_count += 1
            card[f'setName{set_count}'] = set_name[0]
            if len(set_name) > 1: # 세트 각성효과 활성화 되어 있다면
                card[f'setPoint{set_count}'] = int(int_pattern.findall(set_name[1])[0])
            else: # 실제로는 0이 아닐 수 있음, 현 단계에서는 계산 불가(복잡함)
                card[f'setPoint{set_count}'] = 0

    except Exception as e:
        print_preprocessing_exception(fd, '', '', e)
        raise e
        
    try:  
        db, cursor = get_db_cursor()
        sql = f"""
            INSERT INTO lostark.card_table (
                {''.join(f'{key}, ' for key in cards.keys())[:-2]})
            VALUES ({''.join('%s, ' for _ in range(len(cards.keys())))[:-2]});
            """
        values = [card['characterCode'], card['card1_name'], card['card1_level'], card['card2_name'], card['card2_level'], card['card3_name'], card['card3_level'], card['card4_name'], card['card4_level'], card['card5_name'], card['card5_level'], card['card6_name'], card['card6_level'], card['setName1'], card['setPoint1'], card['setName2'], card['setPoint2'], card['setName3'], card['setPoint3'], card['setName4'], card['setPoint4'], card['setName5'], card['setPoint5']] 
        cursor.execute(sql, values)
        db.commit()
        db.close()
    except Exception as e:
        db.rollback()
        db.close()
        print_insert_db_exception(card, e)
        raise e

### 8. Collectible ###
def replace_collectible_key(ct, cdata):
    ck = (ct+"_"+cdata['PointName']).replace('_이그네아의 징표 :', '').replace('_세계수의 잎', '')\
        .replace('_모험물 :', '').replace('_위대한 미술품', '').replace('_오르페우스의 별', '')\
        .replace(' 섬의 마음', ' 섬').replace(' ', '_').replace('#', '').replace('-', '_')
    return ck

def insert_collectible_table(characterCode, data):
    result = check_code_already_in("collectible_table", characterCode)
    if result[0] == 1: return

    ## collectible keys
    # collectibles에는 None 값이 없음
    collectibles = {'characterCode': None}
    for ctype in eval(data):
        ct = ctype['Type']
        for cdata in ctype['CollectiblePoints']:
            ck = replace_collectible_key(ct, cdata)
            collectibles[ck] = None
        
    collectible = collectibles.copy()
    collectible['characterCode'] = characterCode
    try:
        for ctype in eval(data):
            ct = ctype['Type']
            for cdata in ctype['CollectiblePoints']:
                ck = replace_collectible_key(ct, cdata)
                collectible[ck] = cdata['Point']

    except Exception as e:
        traceback.print_exc()
        raise e
        
    try:  
        db, cursor = get_db_cursor()
        sql = f"""
            INSERT INTO lostark.collectible_table (
                {''.join(f'{key}, ' for key in collectibles.keys())[:-2]})
            VALUES ({''.join('%s, ' for _ in range(len(collectibles.keys())))[:-2]});
            """
        values = [collectible['characterCode'], collectible['모코코_씨앗_아르테미스'], collectible['모코코_씨앗_유디아'], collectible['모코코_씨앗_루테란_서부'], collectible['모코코_씨앗_루테란_동부'], collectible['모코코_씨앗_애니츠'], collectible['모코코_씨앗_아르데타인'], collectible['모코코_씨앗_베른_북부'], collectible['모코코_씨앗_슈샤이어'], collectible['모코코_씨앗_로헨델'], collectible['모코코_씨앗_욘'], collectible['모코코_씨앗_페이튼'], collectible['모코코_씨앗_파푸니카'], collectible['모코코_씨앗_베른_남부'], collectible['모코코_씨앗_로웬'], collectible['모코코_씨앗_엘가시아'], collectible['모코코_씨앗_플레체'], collectible['모코코_씨앗_볼다이크'], collectible['모코코_씨앗_대항해'], collectible['섬의_마음_고블린_섬'], collectible['섬의_마음_거대버섯_섬'], collectible['섬의_마음_토토실버_섬'], collectible['섬의_마음_토토피아_섬'], collectible['섬의_마음_환각의_섬'], collectible['섬의_마음_잠자는_노래의_섬'], collectible['섬의_마음_별빛_등대_섬'], collectible['섬의_마음_세월의_섬'], collectible['섬의_마음_볼라르_섬'], collectible['섬의_마음_두키_섬'], collectible['섬의_마음_갈망의_섬'], collectible['섬의_마음_비밀기지_X_301_섬'], collectible['섬의_마음_알트아이젠_섬'], collectible['섬의_마음_칼트헤르츠_섬'], collectible['섬의_마음_안개의_섬'], collectible['섬의_마음_얼음_미로의_섬'], collectible['섬의_마음_얼음과_불의_섬'], collectible['섬의_마음_비키니_아일랜드_섬'], collectible['섬의_마음_그림자의_섬'], collectible['섬의_마음_포르투나_섬'], collectible['섬의_마음_에버그레이스의_둥지_섬'], collectible['섬의_마음_스피다_섬'], collectible['섬의_마음_회상의_섬'], collectible['섬의_마음_포르페_섬'], collectible['섬의_마음_페이토_섬'], collectible['섬의_마음_잊혀진_자들의_도시_섬'], collectible['섬의_마음_검은이빨_주둔지_섬'], collectible['섬의_마음_휴양지_그라비스_섬'], collectible['섬의_마음_외로운_섬_오페르_섬'], collectible['섬의_마음_해바라기_섬'], collectible['섬의_마음_자유의_섬'], collectible['섬의_마음_카마인의_주둔지_섬'], collectible['섬의_마음_죽음의_협곡_섬'], collectible['섬의_마음_작은_행운의_섬'], collectible['섬의_마음_왜곡된_차원의_섬'], collectible['섬의_마음_에라스모의_섬'], collectible['섬의_마음_포모나_섬'], collectible['섬의_마음_도망자들의_마을_섬'], collectible['섬의_마음_메데이아_섬'], collectible['섬의_마음_리베하임_섬'], collectible['섬의_마음_우거진_갈대의_섬'], collectible['섬의_마음_메투스_제도_섬'], collectible['섬의_마음_해적마을_아틀라스_섬'], collectible['섬의_마음_지혜의_섬'], collectible['섬의_마음_신월의_섬'], collectible['섬의_마음_고요의_섬'], collectible['섬의_마음_하얀파도_섬'], collectible['섬의_마음_무법자의_섬'], collectible['섬의_마음_격류의_섬'], collectible['섬의_마음_나루니_섬'], collectible['섬의_마음_노토스_섬'], collectible['섬의_마음_몬테_섬'], collectible['섬의_마음_판다_푸푸_섬'], collectible['섬의_마음_몽환의_섬'], collectible['섬의_마음_하모니_섬'], collectible['섬의_마음_꿈꾸는_갈매기_섬'], collectible['섬의_마음_부서진_빙하의_섬'], collectible['섬의_마음_블루홀_섬'], collectible['섬의_마음_거북_섬'], collectible['섬의_마음_희망의_섬'], collectible['섬의_마음_로팡_섬'], collectible['섬의_마음_고립된_영원의_섬'], collectible['섬의_마음_히프노스의_눈_섬'], collectible['섬의_마음_지고의_섬'], collectible['섬의_마음_그릇된_욕망의_섬'], collectible['섬의_마음_오르비스_섬'], collectible['섬의_마음_에스텔라_섬'], collectible['섬의_마음_슬라임_아일랜드_섬'], collectible['섬의_마음_알라케르_섬'], collectible['섬의_마음_기회의_섬'], collectible['섬의_마음_태초의_섬'], collectible['섬의_마음_황금물결_섬'], collectible['섬의_마음_고요한_안식의_섬'], collectible['섬의_마음_클럽_아비뉴_섬'], collectible['섬의_마음_수라도_섬'], collectible['섬의_마음_기약의_섬'], collectible['섬의_마음_황혼의_섬'], collectible['섬의_마음_아르곤_섬'], collectible['섬의_마음_환영_나비_섬'], collectible['섬의_마음_푸른_바람의_섬'], collectible['섬의_마음_무릉도원_섬'], collectible['섬의_마음_아트로포스_섬'], collectible['섬의_마음_발푸르기스_섬'], collectible['섬의_마음_미지의_섬'], collectible['섬의_마음_그림자달_시장_섬'], collectible['섬의_마음_페르마타_섬'], collectible['섬의_마음_지스브로이_섬'], collectible['섬의_마음_두키_주식회사_섬'], collectible['섬의_마음_속삭이는_작은_섬'], collectible['섬의_마음_비탄의_섬'], collectible['섬의_마음_환죽도_섬'], collectible['섬의_마음_쿵덕쿵_아일랜드_섬'], collectible['섬의_마음_이스테르_섬'], collectible['섬의_마음_스노우팡_아일랜드_섬'], collectible['섬의_마음_모코모코_야시장_섬'], collectible['섬의_마음_꿈꾸는_추억의_섬'], collectible['섬의_마음_잔혹한_장난감_성_섬'], collectible['섬의_마음_모코콩_아일랜드_섬'], collectible['섬의_마음_라일라이_아일랜드_섬'], collectible['섬의_마음_프레테리아_섬'], collectible['위대한_미술품_1'], collectible['위대한_미술품_2'], collectible['위대한_미술품_3'], collectible['위대한_미술품_4'], collectible['위대한_미술품_5'], collectible['위대한_미술품_6'], collectible['위대한_미술품_7'], collectible['위대한_미술품_8'], collectible['위대한_미술품_9'], collectible['위대한_미술품_10'], collectible['위대한_미술품_11'], collectible['위대한_미술품_12'], collectible['위대한_미술품_13'], collectible['위대한_미술품_14'], collectible['위대한_미술품_15'], collectible['위대한_미술품_16'], collectible['위대한_미술품_17'], collectible['위대한_미술품_18'], collectible['위대한_미술품_19'], collectible['위대한_미술품_20'], collectible['위대한_미술품_21'], collectible['위대한_미술품_22'], collectible['위대한_미술품_23'], collectible['위대한_미술품_24'], collectible['위대한_미술품_25'], collectible['위대한_미술품_26'], collectible['위대한_미술품_27'], collectible['위대한_미술품_28'], collectible['위대한_미술품_29'], collectible['위대한_미술품_30'], collectible['위대한_미술품_31'], collectible['위대한_미술품_32'], collectible['위대한_미술품_33'], collectible['위대한_미술품_34'], collectible['위대한_미술품_35'], collectible['위대한_미술품_36'], collectible['위대한_미술품_37'], collectible['위대한_미술품_38'], collectible['위대한_미술품_39'], collectible['위대한_미술품_40'], collectible['위대한_미술품_41'], collectible['위대한_미술품_42'], collectible['위대한_미술품_43'], collectible['위대한_미술품_44'], collectible['위대한_미술품_45'], collectible['위대한_미술품_46'], collectible['위대한_미술품_47'], collectible['위대한_미술품_48'], collectible['위대한_미술품_49'], collectible['위대한_미술품_50'], collectible['위대한_미술품_51'], collectible['위대한_미술품_52'], collectible['위대한_미술품_53'], collectible['위대한_미술품_54'], collectible['위대한_미술품_55'], collectible['위대한_미술품_56'], collectible['위대한_미술품_57'], collectible['위대한_미술품_58'], collectible['위대한_미술품_59'], collectible['위대한_미술품_60'], collectible['거인의_심장_첫_번째_거인의_심장'], collectible['거인의_심장_두_번째_거인의_심장'], collectible['거인의_심장_세_번째_거인의_심장'], collectible['거인의_심장_네_번째_거인의_심장'], collectible['거인의_심장_다섯_번째_거인의_심장'], collectible['거인의_심장_여섯_번째_거인의_심장'], collectible['거인의_심장_일곱_번째_거인의_심장'], collectible['거인의_심장_여덟_번째_거인의_심장'], collectible['거인의_심장_아홉_번째_거인의_심장'], collectible['거인의_심장_열_번째_거인의_심장'], collectible['거인의_심장_열한_번째_거인의_심장'], collectible['거인의_심장_열두_번째_거인의_심장'], collectible['거인의_심장_열세_번째_거인의_심장'], collectible['거인의_심장_열네_번째_거인의_심장'], collectible['거인의_심장_열다섯_번째_거인의_심장'], collectible['이그네아의_징표_아르테미스'], collectible['이그네아의_징표_유디아'], collectible['이그네아의_징표_루테란_서부'], collectible['이그네아의_징표_루테란_동부'], collectible['이그네아의_징표_토토이크'], collectible['이그네아의_징표_애니츠'], collectible['이그네아의_징표_아르데타인'], collectible['이그네아의_징표_베른_북부'], collectible['이그네아의_징표_슈샤이어'], collectible['이그네아의_징표_로헨델'], collectible['이그네아의_징표_욘'], collectible['이그네아의_징표_페이튼'], collectible['이그네아의_징표_파푸니카'], collectible['이그네아의_징표_베른_남부'], collectible['이그네아의_징표_로웬'], collectible['이그네아의_징표_엘가시아'], collectible['이그네아의_징표_볼다이크'], collectible['항해_모험물_모코코_버섯'], collectible['항해_모험물_라마'], collectible['항해_모험물_붉은바다거북'], collectible['항해_모험물_스타더스트'], collectible['항해_모험물_바다꽃'], collectible['항해_모험물_스타후르츠'], collectible['항해_모험물_용과'], collectible['항해_모험물_맨드릴'], collectible['항해_모험물_유령_도마뱀'], collectible['항해_모험물_오색앵무새'], collectible['항해_모험물_바람의_석판'], collectible['항해_모험물_반달_가면'], collectible['항해_모험물_고대_지팡이'], collectible['항해_모험물_고대_금화'], collectible['항해_모험물_잊혀진_호수'], collectible['항해_모험물_크레바스'], collectible['항해_모험물_불타는_얼음'], collectible['항해_모험물_고인돌'], collectible['항해_모험물_마법진'], collectible['항해_모험물_난파선_잔해'], collectible['항해_모험물_참돌고래'], collectible['항해_모험물_극지_맘모스'], collectible['항해_모험물_붉은낙타'], collectible['항해_모험물_유니콘'], collectible['항해_모험물_유령_가오리'], collectible['항해_모험물_세이렌'], collectible['항해_모험물_달의_탑'], collectible['항해_모험물_신의_창'], collectible['항해_모험물_기에나_석상'], collectible['항해_모험물_오로라'], collectible['항해_모험물_소용돌이'], collectible['항해_모험물_침묵하는_섬'], collectible['항해_모험물_토토이끼_배'], collectible['항해_모험물_북해의_눈'], collectible['항해_모험물_남해의_눈'], collectible['항해_모험물_죽은자의_눈'], collectible['항해_모험물_의문의_상자'], collectible['항해_모험물_해적의_의족'], collectible['항해_모험물_해적의_깃발'], collectible['항해_모험물_헤스티아호'], collectible['항해_모험물_환영_나비'], collectible['항해_모험물_대왕_조개'], collectible['항해_모험물_천_덮인_선수상'], collectible['항해_모험물_여인의_얼음_조각상'], collectible['항해_모험물_눈썰매'], collectible['항해_모험물_잃어버린_상선'], collectible['항해_모험물_심해_암석'], collectible['항해_모험물_부서진_거대사슬'], collectible['항해_모험물_가디언의_상흔'], collectible['세계수의_잎_1'], collectible['세계수의_잎_2'], collectible['세계수의_잎_3'], collectible['세계수의_잎_4'], collectible['세계수의_잎_5'], collectible['세계수의_잎_6'], collectible['세계수의_잎_7'], collectible['세계수의_잎_8'], collectible['세계수의_잎_9'], collectible['세계수의_잎_10'], collectible['세계수의_잎_11'], collectible['세계수의_잎_12'], collectible['세계수의_잎_13'], collectible['세계수의_잎_14'], collectible['세계수의_잎_15'], collectible['세계수의_잎_16'], collectible['세계수의_잎_17'], collectible['세계수의_잎_18'], collectible['세계수의_잎_19'], collectible['세계수의_잎_20'], collectible['세계수의_잎_21'], collectible['세계수의_잎_22'], collectible['세계수의_잎_23'], collectible['세계수의_잎_24'], collectible['세계수의_잎_25'], collectible['세계수의_잎_26'], collectible['세계수의_잎_27'], collectible['세계수의_잎_28'], collectible['세계수의_잎_29'], collectible['세계수의_잎_30'], collectible['세계수의_잎_31'], collectible['세계수의_잎_41'], collectible['세계수의_잎_42'], collectible['세계수의_잎_43'], collectible['세계수의_잎_44'], collectible['세계수의_잎_45'], collectible['세계수의_잎_46'], collectible['세계수의_잎_50'], collectible['세계수의_잎_51'], collectible['세계수의_잎_52'], collectible['세계수의_잎_53'], collectible['세계수의_잎_54'], collectible['세계수의_잎_55'], collectible['세계수의_잎_59'], collectible['세계수의_잎_60'], collectible['세계수의_잎_61'], collectible['세계수의_잎_62'], collectible['세계수의_잎_63'], collectible['세계수의_잎_64'], collectible['세계수의_잎_68'], collectible['세계수의_잎_69'], collectible['세계수의_잎_70'], collectible['세계수의_잎_71'], collectible['세계수의_잎_72'], collectible['세계수의_잎_73'], collectible['세계수의_잎_74'], collectible['세계수의_잎_75'], collectible['세계수의_잎_76'], collectible['세계수의_잎_77'], collectible['세계수의_잎_78'], collectible['세계수의_잎_79'], collectible['세계수의_잎_80'], collectible['세계수의_잎_81'], collectible['세계수의_잎_82'], collectible['세계수의_잎_83'], collectible['세계수의_잎_84'], collectible['세계수의_잎_85'], collectible['세계수의_잎_86'], collectible['세계수의_잎_87'], collectible['세계수의_잎_88'], collectible['세계수의_잎_89'], collectible['세계수의_잎_90'], collectible['세계수의_잎_91'], collectible['세계수의_잎_92'], collectible['세계수의_잎_93'], collectible['세계수의_잎_94'], collectible['세계수의_잎_95'], collectible['세계수의_잎_96'], collectible['세계수의_잎_97'], collectible['세계수의_잎_98'], collectible['세계수의_잎_99'], collectible['세계수의_잎_100'], collectible['세계수의_잎_101'], collectible['세계수의_잎_102'], collectible['세계수의_잎_103'], collectible['세계수의_잎_104'], collectible['세계수의_잎_105'], collectible['세계수의_잎_106'], collectible['세계수의_잎_107'], collectible['세계수의_잎_108'], collectible['세계수의_잎_109'], collectible['오르페우스의_별_1'], collectible['오르페우스의_별_2'], collectible['오르페우스의_별_3'], collectible['오르페우스의_별_4'], collectible['오르페우스의_별_5'], collectible['오르페우스의_별_6'], collectible['오르페우스의_별_7'], collectible['오르페우스의_별_8'], collectible['오르페우스의_별_9'], collectible['오르페우스의_별_10'], collectible['기억의_오르골_기억의_구슬_1'], collectible['기억의_오르골_기억의_구슬_2'], collectible['기억의_오르골_기억의_구슬_3'], collectible['기억의_오르골_기억의_구슬_4'], collectible['기억의_오르골_기억의_구슬_5'], collectible['기억의_오르골_기억의_구슬_6'], collectible['기억의_오르골_기억의_구슬_7'], collectible['기억의_오르골_기억의_구슬_8'], collectible['기억의_오르골_기억의_구슬_9'], collectible['기억의_오르골_기억의_구슬_10']]
        cursor.execute(sql, values)
        db.commit()
        db.close()
    except Exception as e:
        db.rollback()
        db.close()
        print_insert_db_exception(collectible, e)
        raise e

### 9. colosseum ###
def insert_colosseum_table(characterCode, data):
    result = check_code_already_in("colosseum_table", characterCode)
    if result[0] == 1: return
    ## colosseum keys

    seasons = ['preSeason']
    for i in range(1, len(eval(data)['Colosseums'])): 
        seasons.append(f'season{i}')
    # CoOpBattle, Competitive, DeathMatch, SeasonName, TeamDeathMatch, TeamElimination
    dic_keys = ['CoOpBattle_AceCount','CoOpBattle_DeathCount','CoOpBattle_KillCount','CoOpBattle_LoseCount',
                'CoOpBattle_PlayCount','CoOpBattle_TieCount','CoOpBattle_VictoryCount','Competitive_AceCount',
                'Competitive_DeathCount','Competitive_KillCount','Competitive_LoseCount','Competitive_PlayCount',
                'Competitive_Rank','Competitive_RankLastMmr','Competitive_RankName','Competitive_TieCount',
                'Competitive_VictoryCount','Deathmatch_AceCount','Deathmatch_DeathCount','Deathmatch_KillCount',
                'Deathmatch_LoseCount','Deathmatch_PlayCount','Deathmatch_TieCount','Deathmatch_VictoryCount',
                'TeamDeathmatch_AceCount','TeamDeathmatch_DeathCount','TeamDeathmatch_KillCount',
                'TeamDeathmatch_LoseCount','TeamDeathmatch_PlayCount','TeamDeathmatch_TieCount',
                'TeamDeathmatch_VictoryCount','TeamElimination_AceCount','TeamElimination_AllKillCount',
                'TeamElimination_DeathCount','TeamElimination_FirstPlayCount','TeamElimination_FirstWinCount',
                'TeamElimination_KillCount','TeamElimination_LoseCount','TeamElimination_PlayCount',
                'TeamElimination_SecondPlayCount','TeamElimination_SecondWinCount','TeamElimination_ThirdPlayCount',
                'TeamElimination_ThirdWinCount','TeamElimination_TieCount','TeamElimination_VictoryCount']
    colosseums = {'characterCode': None, 'exp':None, 'preRank':None, 'rank':None}
    for s in seasons:
        for key in dic_keys:
            colosseums[s+'_'+key] = None
        
    colosseum = colosseums.copy()
    colosseum['characterCode'] = characterCode
    try:
        cdf = eval(data)
        if cdf==None: return
        colosseum['exp'] = cdf['Exp']
        colosseum['preRank'] = cdf['PreRank']
        colosseum['rank'] = cdf['Rank']
        for cidx in range(len(cdf['Colosseums'])):
            if cidx == 0: season_name ='preSeason'
            else: season_name = f'시즌{cidx}'
            for k, v in cdf['Colosseums'][cidx].items():
                sk = str(k)
                sv = str(v)
                if (v != None) & ('시즌' not in sv):
                    for ck, cv in v.items():
                        if ck != 'RankIcon':
                            colosseum[season_name+'_'+sk+'_'+ck] = cv
    except Exception as e:
        print_preprocessing_exception(cdf, sk, sv, e)
        raise e
        
    try:  
        db, cursor = get_db_cursor()
        sql = f"""
            INSERT INTO lostark.colosseum_table (
                {''.join(f'`{key}`, ' for key in colosseums.keys())[:-2]})
            VALUES ({''.join('%s, ' for _ in range(len(colosseums.keys())))[:-2]});
            """
        values = [colosseum['characterCode'], colosseum['exp'], colosseum['preRank'], colosseum['rank'], colosseum['preSeason_CoOpBattle_AceCount'], colosseum['preSeason_CoOpBattle_DeathCount'], colosseum['preSeason_CoOpBattle_KillCount'], colosseum['preSeason_CoOpBattle_LoseCount'], colosseum['preSeason_CoOpBattle_PlayCount'], colosseum['preSeason_CoOpBattle_TieCount'], colosseum['preSeason_CoOpBattle_VictoryCount'], colosseum['preSeason_Competitive_AceCount'], colosseum['preSeason_Competitive_DeathCount'], colosseum['preSeason_Competitive_KillCount'], colosseum['preSeason_Competitive_LoseCount'], colosseum['preSeason_Competitive_PlayCount'], colosseum['preSeason_Competitive_Rank'], colosseum['preSeason_Competitive_RankLastMmr'], colosseum['preSeason_Competitive_RankName'], colosseum['preSeason_Competitive_TieCount'], colosseum['preSeason_Competitive_VictoryCount'], colosseum['preSeason_Deathmatch_AceCount'], colosseum['preSeason_Deathmatch_DeathCount'], colosseum['preSeason_Deathmatch_KillCount'], colosseum['preSeason_Deathmatch_LoseCount'], colosseum['preSeason_Deathmatch_PlayCount'], colosseum['preSeason_Deathmatch_TieCount'], colosseum['preSeason_Deathmatch_VictoryCount'], colosseum['preSeason_TeamDeathmatch_AceCount'], colosseum['preSeason_TeamDeathmatch_DeathCount'], colosseum['preSeason_TeamDeathmatch_KillCount'], colosseum['preSeason_TeamDeathmatch_LoseCount'], colosseum['preSeason_TeamDeathmatch_PlayCount'], colosseum['preSeason_TeamDeathmatch_TieCount'], colosseum['preSeason_TeamDeathmatch_VictoryCount'], colosseum['preSeason_TeamElimination_AceCount'], colosseum['preSeason_TeamElimination_AllKillCount'], colosseum['preSeason_TeamElimination_DeathCount'], colosseum['preSeason_TeamElimination_FirstPlayCount'], colosseum['preSeason_TeamElimination_FirstWinCount'], colosseum['preSeason_TeamElimination_KillCount'], colosseum['preSeason_TeamElimination_LoseCount'], colosseum['preSeason_TeamElimination_PlayCount'], colosseum['preSeason_TeamElimination_SecondPlayCount'], colosseum['preSeason_TeamElimination_SecondWinCount'], colosseum['preSeason_TeamElimination_ThirdPlayCount'], colosseum['preSeason_TeamElimination_ThirdWinCount'], colosseum['preSeason_TeamElimination_TieCount'], colosseum['preSeason_TeamElimination_VictoryCount'], colosseum['season1_CoOpBattle_AceCount'], colosseum['season1_CoOpBattle_DeathCount'], colosseum['season1_CoOpBattle_KillCount'], colosseum['season1_CoOpBattle_LoseCount'], colosseum['season1_CoOpBattle_PlayCount'], colosseum['season1_CoOpBattle_TieCount'], colosseum['season1_CoOpBattle_VictoryCount'], colosseum['season1_Competitive_AceCount'], colosseum['season1_Competitive_DeathCount'], colosseum['season1_Competitive_KillCount'], colosseum['season1_Competitive_LoseCount'], colosseum['season1_Competitive_PlayCount'], colosseum['season1_Competitive_Rank'], colosseum['season1_Competitive_RankLastMmr'], colosseum['season1_Competitive_RankName'], colosseum['season1_Competitive_TieCount'], colosseum['season1_Competitive_VictoryCount'], colosseum['season1_Deathmatch_AceCount'], colosseum['season1_Deathmatch_DeathCount'], colosseum['season1_Deathmatch_KillCount'], colosseum['season1_Deathmatch_LoseCount'], colosseum['season1_Deathmatch_PlayCount'], colosseum['season1_Deathmatch_TieCount'], colosseum['season1_Deathmatch_VictoryCount'], colosseum['season1_TeamDeathmatch_AceCount'], colosseum['season1_TeamDeathmatch_DeathCount'], colosseum['season1_TeamDeathmatch_KillCount'], colosseum['season1_TeamDeathmatch_LoseCount'], colosseum['season1_TeamDeathmatch_PlayCount'], colosseum['season1_TeamDeathmatch_TieCount'], colosseum['season1_TeamDeathmatch_VictoryCount'], colosseum['season1_TeamElimination_AceCount'], colosseum['season1_TeamElimination_AllKillCount'], colosseum['season1_TeamElimination_DeathCount'], colosseum['season1_TeamElimination_FirstPlayCount'], colosseum['season1_TeamElimination_FirstWinCount'], colosseum['season1_TeamElimination_KillCount'], colosseum['season1_TeamElimination_LoseCount'], colosseum['season1_TeamElimination_PlayCount'], colosseum['season1_TeamElimination_SecondPlayCount'], colosseum['season1_TeamElimination_SecondWinCount'], colosseum['season1_TeamElimination_ThirdPlayCount'], colosseum['season1_TeamElimination_ThirdWinCount'], colosseum['season1_TeamElimination_TieCount'], colosseum['season1_TeamElimination_VictoryCount'], colosseum['season2_CoOpBattle_AceCount'], colosseum['season2_CoOpBattle_DeathCount'], colosseum['season2_CoOpBattle_KillCount'], colosseum['season2_CoOpBattle_LoseCount'], colosseum['season2_CoOpBattle_PlayCount'], colosseum['season2_CoOpBattle_TieCount'], colosseum['season2_CoOpBattle_VictoryCount'], colosseum['season2_Competitive_AceCount'], colosseum['season2_Competitive_DeathCount'], colosseum['season2_Competitive_KillCount'], colosseum['season2_Competitive_LoseCount'], colosseum['season2_Competitive_PlayCount'], colosseum['season2_Competitive_Rank'], colosseum['season2_Competitive_RankLastMmr'], colosseum['season2_Competitive_RankName'], colosseum['season2_Competitive_TieCount'], colosseum['season2_Competitive_VictoryCount'], colosseum['season2_Deathmatch_AceCount'], colosseum['season2_Deathmatch_DeathCount'], colosseum['season2_Deathmatch_KillCount'], colosseum['season2_Deathmatch_LoseCount'], colosseum['season2_Deathmatch_PlayCount'], colosseum['season2_Deathmatch_TieCount'], colosseum['season2_Deathmatch_VictoryCount'], colosseum['season2_TeamDeathmatch_AceCount'], colosseum['season2_TeamDeathmatch_DeathCount'], colosseum['season2_TeamDeathmatch_KillCount'], colosseum['season2_TeamDeathmatch_LoseCount'], colosseum['season2_TeamDeathmatch_PlayCount'], colosseum['season2_TeamDeathmatch_TieCount'], colosseum['season2_TeamDeathmatch_VictoryCount'], colosseum['season2_TeamElimination_AceCount'], colosseum['season2_TeamElimination_AllKillCount'], colosseum['season2_TeamElimination_DeathCount'], colosseum['season2_TeamElimination_FirstPlayCount'], colosseum['season2_TeamElimination_FirstWinCount'], colosseum['season2_TeamElimination_KillCount'], colosseum['season2_TeamElimination_LoseCount'], colosseum['season2_TeamElimination_PlayCount'], colosseum['season2_TeamElimination_SecondPlayCount'], colosseum['season2_TeamElimination_SecondWinCount'], colosseum['season2_TeamElimination_ThirdPlayCount'], colosseum['season2_TeamElimination_ThirdWinCount'], colosseum['season2_TeamElimination_TieCount'], colosseum['season2_TeamElimination_VictoryCount'], colosseum['season3_CoOpBattle_AceCount'], colosseum['season3_CoOpBattle_DeathCount'], colosseum['season3_CoOpBattle_KillCount'], colosseum['season3_CoOpBattle_LoseCount'], colosseum['season3_CoOpBattle_PlayCount'], colosseum['season3_CoOpBattle_TieCount'], colosseum['season3_CoOpBattle_VictoryCount'], colosseum['season3_Competitive_AceCount'], colosseum['season3_Competitive_DeathCount'], colosseum['season3_Competitive_KillCount'], colosseum['season3_Competitive_LoseCount'], colosseum['season3_Competitive_PlayCount'], colosseum['season3_Competitive_Rank'], colosseum['season3_Competitive_RankLastMmr'], colosseum['season3_Competitive_RankName'], colosseum['season3_Competitive_TieCount'], colosseum['season3_Competitive_VictoryCount'], colosseum['season3_Deathmatch_AceCount'], colosseum['season3_Deathmatch_DeathCount'], colosseum['season3_Deathmatch_KillCount'], colosseum['season3_Deathmatch_LoseCount'], colosseum['season3_Deathmatch_PlayCount'], colosseum['season3_Deathmatch_TieCount'], colosseum['season3_Deathmatch_VictoryCount'], colosseum['season3_TeamDeathmatch_AceCount'], colosseum['season3_TeamDeathmatch_DeathCount'], colosseum['season3_TeamDeathmatch_KillCount'], colosseum['season3_TeamDeathmatch_LoseCount'], colosseum['season3_TeamDeathmatch_PlayCount'], colosseum['season3_TeamDeathmatch_TieCount'], colosseum['season3_TeamDeathmatch_VictoryCount'], colosseum['season3_TeamElimination_AceCount'], colosseum['season3_TeamElimination_AllKillCount'], colosseum['season3_TeamElimination_DeathCount'], colosseum['season3_TeamElimination_FirstPlayCount'], colosseum['season3_TeamElimination_FirstWinCount'], colosseum['season3_TeamElimination_KillCount'], colosseum['season3_TeamElimination_LoseCount'], colosseum['season3_TeamElimination_PlayCount'], colosseum['season3_TeamElimination_SecondPlayCount'], colosseum['season3_TeamElimination_SecondWinCount'], colosseum['season3_TeamElimination_ThirdPlayCount'], colosseum['season3_TeamElimination_ThirdWinCount'], colosseum['season3_TeamElimination_TieCount'], colosseum['season3_TeamElimination_VictoryCount'], colosseum['season4_CoOpBattle_AceCount'], colosseum['season4_CoOpBattle_DeathCount'], colosseum['season4_CoOpBattle_KillCount'], colosseum['season4_CoOpBattle_LoseCount'], colosseum['season4_CoOpBattle_PlayCount'], colosseum['season4_CoOpBattle_TieCount'], colosseum['season4_CoOpBattle_VictoryCount'], colosseum['season4_Competitive_AceCount'], colosseum['season4_Competitive_DeathCount'], colosseum['season4_Competitive_KillCount'], colosseum['season4_Competitive_LoseCount'], colosseum['season4_Competitive_PlayCount'], colosseum['season4_Competitive_Rank'], colosseum['season4_Competitive_RankLastMmr'], colosseum['season4_Competitive_RankName'], colosseum['season4_Competitive_TieCount'], colosseum['season4_Competitive_VictoryCount'], colosseum['season4_Deathmatch_AceCount'], colosseum['season4_Deathmatch_DeathCount'], colosseum['season4_Deathmatch_KillCount'], colosseum['season4_Deathmatch_LoseCount'], colosseum['season4_Deathmatch_PlayCount'], colosseum['season4_Deathmatch_TieCount'], colosseum['season4_Deathmatch_VictoryCount'], colosseum['season4_TeamDeathmatch_AceCount'], colosseum['season4_TeamDeathmatch_DeathCount'], colosseum['season4_TeamDeathmatch_KillCount'], colosseum['season4_TeamDeathmatch_LoseCount'], colosseum['season4_TeamDeathmatch_PlayCount'], colosseum['season4_TeamDeathmatch_TieCount'], colosseum['season4_TeamDeathmatch_VictoryCount'], colosseum['season4_TeamElimination_AceCount'], colosseum['season4_TeamElimination_AllKillCount'], colosseum['season4_TeamElimination_DeathCount'], colosseum['season4_TeamElimination_FirstPlayCount'], colosseum['season4_TeamElimination_FirstWinCount'], colosseum['season4_TeamElimination_KillCount'], colosseum['season4_TeamElimination_LoseCount'], colosseum['season4_TeamElimination_PlayCount'], colosseum['season4_TeamElimination_SecondPlayCount'], colosseum['season4_TeamElimination_SecondWinCount'], colosseum['season4_TeamElimination_ThirdPlayCount'], colosseum['season4_TeamElimination_ThirdWinCount'], colosseum['season4_TeamElimination_TieCount'], colosseum['season4_TeamElimination_VictoryCount'], colosseum['season5_CoOpBattle_AceCount'], colosseum['season5_CoOpBattle_DeathCount'], colosseum['season5_CoOpBattle_KillCount'], colosseum['season5_CoOpBattle_LoseCount'], colosseum['season5_CoOpBattle_PlayCount'], colosseum['season5_CoOpBattle_TieCount'], colosseum['season5_CoOpBattle_VictoryCount'], colosseum['season5_Competitive_AceCount'], colosseum['season5_Competitive_DeathCount'], colosseum['season5_Competitive_KillCount'], colosseum['season5_Competitive_LoseCount'], colosseum['season5_Competitive_PlayCount'], colosseum['season5_Competitive_Rank'], colosseum['season5_Competitive_RankLastMmr'], colosseum['season5_Competitive_RankName'], colosseum['season5_Competitive_TieCount'], colosseum['season5_Competitive_VictoryCount'], colosseum['season5_Deathmatch_AceCount'], colosseum['season5_Deathmatch_DeathCount'], colosseum['season5_Deathmatch_KillCount'], colosseum['season5_Deathmatch_LoseCount'], colosseum['season5_Deathmatch_PlayCount'], colosseum['season5_Deathmatch_TieCount'], colosseum['season5_Deathmatch_VictoryCount'], colosseum['season5_TeamDeathmatch_AceCount'], colosseum['season5_TeamDeathmatch_DeathCount'], colosseum['season5_TeamDeathmatch_KillCount'], colosseum['season5_TeamDeathmatch_LoseCount'], colosseum['season5_TeamDeathmatch_PlayCount'], colosseum['season5_TeamDeathmatch_TieCount'], colosseum['season5_TeamDeathmatch_VictoryCount'], colosseum['season5_TeamElimination_AceCount'], colosseum['season5_TeamElimination_AllKillCount'], colosseum['season5_TeamElimination_DeathCount'], colosseum['season5_TeamElimination_FirstPlayCount'], colosseum['season5_TeamElimination_FirstWinCount'], colosseum['season5_TeamElimination_KillCount'], colosseum['season5_TeamElimination_LoseCount'], colosseum['season5_TeamElimination_PlayCount'], colosseum['season5_TeamElimination_SecondPlayCount'], colosseum['season5_TeamElimination_SecondWinCount'], colosseum['season5_TeamElimination_ThirdPlayCount'], colosseum['season5_TeamElimination_ThirdWinCount'], colosseum['season5_TeamElimination_TieCount'], colosseum['season5_TeamElimination_VictoryCount'], colosseum['season6_CoOpBattle_AceCount'], colosseum['season6_CoOpBattle_DeathCount'], colosseum['season6_CoOpBattle_KillCount'], colosseum['season6_CoOpBattle_LoseCount'], colosseum['season6_CoOpBattle_PlayCount'], colosseum['season6_CoOpBattle_TieCount'], colosseum['season6_CoOpBattle_VictoryCount'], colosseum['season6_Competitive_AceCount'], colosseum['season6_Competitive_DeathCount'], colosseum['season6_Competitive_KillCount'], colosseum['season6_Competitive_LoseCount'], colosseum['season6_Competitive_PlayCount'], colosseum['season6_Competitive_Rank'], colosseum['season6_Competitive_RankLastMmr'], colosseum['season6_Competitive_RankName'], colosseum['season6_Competitive_TieCount'], colosseum['season6_Competitive_VictoryCount'], colosseum['season6_Deathmatch_AceCount'], colosseum['season6_Deathmatch_DeathCount'], colosseum['season6_Deathmatch_KillCount'], colosseum['season6_Deathmatch_LoseCount'], colosseum['season6_Deathmatch_PlayCount'], colosseum['season6_Deathmatch_TieCount'], colosseum['season6_Deathmatch_VictoryCount'], colosseum['season6_TeamDeathmatch_AceCount'], colosseum['season6_TeamDeathmatch_DeathCount'], colosseum['season6_TeamDeathmatch_KillCount'], colosseum['season6_TeamDeathmatch_LoseCount'], colosseum['season6_TeamDeathmatch_PlayCount'], colosseum['season6_TeamDeathmatch_TieCount'], colosseum['season6_TeamDeathmatch_VictoryCount'], colosseum['season6_TeamElimination_AceCount'], colosseum['season6_TeamElimination_AllKillCount'], colosseum['season6_TeamElimination_DeathCount'], colosseum['season6_TeamElimination_FirstPlayCount'], colosseum['season6_TeamElimination_FirstWinCount'], colosseum['season6_TeamElimination_KillCount'], colosseum['season6_TeamElimination_LoseCount'], colosseum['season6_TeamElimination_PlayCount'], colosseum['season6_TeamElimination_SecondPlayCount'], colosseum['season6_TeamElimination_SecondWinCount'], colosseum['season6_TeamElimination_ThirdPlayCount'], colosseum['season6_TeamElimination_ThirdWinCount'], colosseum['season6_TeamElimination_TieCount'], colosseum['season6_TeamElimination_VictoryCount'], colosseum['season7_CoOpBattle_AceCount'], colosseum['season7_CoOpBattle_DeathCount'], colosseum['season7_CoOpBattle_KillCount'], colosseum['season7_CoOpBattle_LoseCount'], colosseum['season7_CoOpBattle_PlayCount'], colosseum['season7_CoOpBattle_TieCount'], colosseum['season7_CoOpBattle_VictoryCount'], colosseum['season7_Competitive_AceCount'], colosseum['season7_Competitive_DeathCount'], colosseum['season7_Competitive_KillCount'], colosseum['season7_Competitive_LoseCount'], colosseum['season7_Competitive_PlayCount'], colosseum['season7_Competitive_Rank'], colosseum['season7_Competitive_RankLastMmr'], colosseum['season7_Competitive_RankName'], colosseum['season7_Competitive_TieCount'], colosseum['season7_Competitive_VictoryCount'], colosseum['season7_Deathmatch_AceCount'], colosseum['season7_Deathmatch_DeathCount'], colosseum['season7_Deathmatch_KillCount'], colosseum['season7_Deathmatch_LoseCount'], colosseum['season7_Deathmatch_PlayCount'], colosseum['season7_Deathmatch_TieCount'], colosseum['season7_Deathmatch_VictoryCount'], colosseum['season7_TeamDeathmatch_AceCount'], colosseum['season7_TeamDeathmatch_DeathCount'], colosseum['season7_TeamDeathmatch_KillCount'], colosseum['season7_TeamDeathmatch_LoseCount'], colosseum['season7_TeamDeathmatch_PlayCount'], colosseum['season7_TeamDeathmatch_TieCount'], colosseum['season7_TeamDeathmatch_VictoryCount'], colosseum['season7_TeamElimination_AceCount'], colosseum['season7_TeamElimination_AllKillCount'], colosseum['season7_TeamElimination_DeathCount'], colosseum['season7_TeamElimination_FirstPlayCount'], colosseum['season7_TeamElimination_FirstWinCount'], colosseum['season7_TeamElimination_KillCount'], colosseum['season7_TeamElimination_LoseCount'], colosseum['season7_TeamElimination_PlayCount'], colosseum['season7_TeamElimination_SecondPlayCount'], colosseum['season7_TeamElimination_SecondWinCount'], colosseum['season7_TeamElimination_ThirdPlayCount'], colosseum['season7_TeamElimination_ThirdWinCount'], colosseum['season7_TeamElimination_TieCount'], colosseum['season7_TeamElimination_VictoryCount']]
        cursor.execute(sql, values)
        db.commit()
        db.close()
    except Exception as e:
        db.rollback()
        db.close()
        print_insert_db_exception(colosseum, e)
        raise e

## 10. all ###
def insert_all_table(df):
    characterCode = df['characterCode'][0]
    try:
        insert_profile_stats_table(characterCode, df['ArmoryProfile'][0])
        insert_avatar_table(characterCode, df['ArmoryAvatars'][0])
        insert_equipment_accessory_sequipment_table(characterCode, df['ArmoryEquipment'][0])
        insert_skill_table(characterCode, df['ArmorySkills'][0])
        insert_gem_table(characterCode, df['ArmoryGem'][0])
        insert_engraving_table(characterCode, df['ArmoryEngraving'][0])
        insert_card_table(characterCode, df['ArmoryCard'][0])
        insert_collectible_table(characterCode, df['Collectibles'][0])
        insert_colosseum_table(characterCode, df['ColosseumInfo'][0])
    except Exception as e:
        raise e

# predict df
def get_predict_df(characterName):
    tables = ['profile_table','accessory_table', 'avatar_table', 'card_table', 'engraving_table', 
            'equipment_table', 'gem_table', 'skill_table', 'stats_table']
    accessories = ['목걸이', '귀걸이1', '귀걸이2', '반지1', '반지2']
    accessory_column = ['_quality', '_grade', '_tier']
    avatars = ['무기1', '무기2', '상의1', '상의2', '하의1', '하의2']
    avatar_column = ['_grade']
    equipments = ['무기', '투구', '어깨', '상의', '하의', '장갑']
    equipment_column = ['_quality', '_grade', '_setLevel']
    gem_column = ['_grade', '_level', '_tier']
    stat_column = ['치명', '특화', '신속', '제압', '인내', '숙련']

    sql = f"""SELECT profile_table.characterCode, profile_table.expeditionLevel, profile_table.totalSkillPoint,
    profile_table.characterLevel, profile_table.itemMaxLevel,

    {', '.join(f"accessory_table.{accessory}{column}" for accessory in accessories for column in accessory_column)},

    {', '.join(f"avatar_table.{avatar}{column}" for avatar in avatars for column in avatar_column)},

    {', '.join(f"card_table.setName{i}, card_table.setPoint{i}" for i in range(1, 5))},

    {', '.join(f"engraving_table.grantName{i}, engraving_table.grantPoint{i}" for i in range(1, 3))},
    {', '.join(f"engraving_table.engraving{i}_name, engraving_table.engraving{i}_level" for i in range(1, 12))},

    {', '.join(f"equipment_table.{equipment}{column}" for equipment in equipments for column in equipment_column)},

    {', '.join(f"gem_table.gem{i}{column}" for i in range(1, 12) for column in gem_column)},

    {', '.join(f"skill_table.skill{i}_tripod{j}_point" for i in range(1, 17) for j in range(1, 4))},

    {', '.join(f"stats_table.{column}_값" for column in stat_column)}

    FROM profile_table
    {' '.join(f"LEFT JOIN {tables[i+1]} ON {tables[i]}.characterCode = {tables[i+1]}.characterCode"
    for i in range(len(tables)-1))}
    WHERE lostark.profile_table.characterName = '{characterName}';
    """
    db, cursor = get_db_cursor()
    cursor.execute(sql)
    df = pd.DataFrame(cursor.fetchall())
    db.close()

    columns = ["characterCode", "expeditionLevel", "totalSkillPoint", "characterLevel", "itemMaxLevel"]
    for accessory in accessories:
        for column in accessory_column:
            columns.append(f"{accessory}{column}")
    for avatar in avatars :
        for column in avatar_column:
            columns.append(f"avatar_{avatar}{column}") 
    for i in range(1, 5):
        columns.append(f"card_setName{i}")
        columns.append(f"card_setPoint{i}")
    for i in range(1, 3):
        columns.append(f"engraving_grantName{i}")
        columns.append(f"engraving_grantPoint{i}")
    for i in range(1, 12):
        columns.append(f"engraving{i}_name")
        columns.append(f"engraving{i}_level")
    for equipment in equipments:
        for column in equipment_column:
            columns.append(f"equipment_{equipment}{column}")
    for i in range(1, 12):
        for column in gem_column:
            columns.append(f"gem{i}{column}")
    for i in range(1, 17):
        for j in range(1, 4):
            columns.append(f"skill{i}_tripod{j}_point")
    for column in stat_column:
        columns.append(f"{column}_값")
    df.columns = columns
    display(df)
    
    
    from sklearn.preprocessing import LabelEncoder
    grade_label = joblib.load("C:\\Users\\user\\Code_Files_Jupyter\\Lostark\\Lostark-API-DA\\label\\grade_label.pkl")
    card_label = joblib.load("C:\\Users\\user\\Code_Files_Jupyter\\Lostark\\Lostark-API-DA\\label\\card_label.pkl")
    engraving_label = joblib.load("C:\\Users\\user\\Code_Files_Jupyter\\Lostark\\Lostark-API-DA\\label\\engraving_label.pkl")
    
    df['itemMaxLevel'] = df['itemMaxLevel'].astype('float64')
    for accessory in accessories:
        df[f'{accessory}_quality'] = df[f'{accessory}_quality'].fillna(-1).astype('int64')
        df[f'{accessory}_grade'] = grade_label.transform(df[f'{accessory}_grade'].fillna('None'))
        df[f'{accessory}_tier'] = df[f'{accessory}_tier'].fillna(-1).astype('int64')
    for avatar in avatars :
        df[f"avatar_{avatar}_grade"] =  grade_label.transform(df[f"avatar_{avatar}_grade"].fillna('None'))
    for i in range(1, 5):
        df[f"card_setName{i}"] = card_label.transform(df[f"card_setName{i}"].fillna('None'))
        df[f"card_setPoint{i}"] = df[f"card_setPoint{i}"].fillna(-1).astype('int64')
    for i in range(1, 3):
        df[f"engraving_grantName{i}"] = engraving_label.transform(df[f"engraving_grantName{i}"].fillna('None'))
        df[f"engraving_grantPoint{i}"] = df[f"engraving_grantPoint{i}"].fillna('-1').astype('int64')
    for i in range(1, 12):
        df[f"engraving{i}_name"] = engraving_label.transform(df[f"engraving{i}_name"].fillna('None'))
        df[f"engraving{i}_level"] = df[f"engraving{i}_level"].fillna(-1).astype('int64')
    for equipment in equipments:
        df[f"equipment_{equipment}_grade"] = grade_label.transform(df[f"equipment_{equipment}_grade"].fillna('None'))  
        df[f"equipment_{equipment}_setLevel"] = df[f"equipment_{equipment}_setLevel"].fillna(-1).astype('int64')
        df[f"equipment_{equipment}_quality"] = df[f"equipment_{equipment}_quality"].fillna(-1).astype('int64')
    for i in range(1, 12):
        df[f"gem{i}_grade"] = grade_label.transform(df[f"gem{i}_grade"].fillna('None'))
        df[f"gem{i}_level"] = df[f"gem{i}_level"].fillna(-1).astype('int64')
        df[f"gem{i}_tier"] = df[f"gem{i}_tier"].fillna(-1).astype('int64')
    for i in range(1, 17):
        for j in range(1, 4):
            df[f"skill{i}_tripod{j}_point"] = df[f"skill{i}_tripod{j}_point"].fillna(-1).astype('int64')
        
#     from sklearn.preprocessing import StandardScaler
#     scaler = joblib.load("C:\\Users\\user\\Code_Files_Jupyter\\Lostark\\Lostark-API-DA\\Scaler\\Scaler.pkl")

#     df_scale = scaler.transform(df)
#     df_scale = pd.DataFrame(df_scale, columns=df.columns)
    
#     dfc = df.copy()
#     from sklearn.decomposition import PCA
#     # gem grade
#     pca = joblib.load("C:\\Users\\user\\Code_Files_Jupyter\\Lostark\\Lostark-API-DA\\PCA\\gem_grade_PCA.pkl")
#     columns = [f'gem{i}_grade' for i in range(1, 12)]
#     df_pca = pca.transform(df_scale[columns])
#     dfc.drop(columns, axis=1, inplace=True)
#     df_pca = pd.DataFrame(df_pca, columns=['gem_grade_PCA1', 'gem_grade_PCA2'])
#     dfc = pd.concat([dfc, df_pca], axis=1)

#     # gem tier
#     pca = joblib.load("C:\\Users\\user\\Code_Files_Jupyter\\Lostark\\Lostark-API-DA\\PCA\\gem_tier_PCA.pkl")
#     columns = [f'gem{i}_tier' for i in range(1, 12)]
#     df_pca = pca.transform(df_scale[columns])
#     dfc.drop(columns, axis=1, inplace=True)
#     df_pca = pd.DataFrame(df_pca, columns=['gem_tier_PCA1', 'gem_tier_PCA2', 'gem_tier_PCA3'])
#     dfc = pd.concat([dfc, df_pca], axis=1)

#     # gem level
#     pca = joblib.load("C:\\Users\\user\\Code_Files_Jupyter\\Lostark\\Lostark-API-DA\\PCA\\gem_level_PCA.pkl")
#     columns = [f'gem{i}_level' for i in range(1, 12)]
#     df_pca = pca.transform(df_scale[columns])
#     dfc.drop(columns, axis=1, inplace=True)
#     df_pca = pd.DataFrame(df_pca, columns=['gem_level_PCA1', 'gem_level_PCA2'])
#     dfc = pd.concat([dfc, df_pca], axis=1)
    
#     # skill tripod point
#     pca = joblib.load("C:\\Users\\user\\Code_Files_Jupyter\\Lostark\\Lostark-API-DA\\PCA\\skill_PCA.pkl")
#     columns = [f'skill{i}_tripod{j}_point' for i in range(9, 17) for j in range(1, 4)]
#     df_pca = pca.transform(df_scale[columns])
#     dfc.drop(columns, axis=1, inplace=True)
#     df_pca = pd.DataFrame(df_pca, columns=['skill_tripod_point_PCA1', 'skill_tripod_point_PCA2',
#         'skill_tripod_point_PCA3', 'skill_tripod_point_PCA4'])
#     dfc = pd.concat([dfc, df_pca], axis=1)

#     # equipment grade
#     pca = joblib.load("C:\\Users\\user\\Code_Files_Jupyter\\Lostark\\Lostark-API-DA\\PCA\\equipment_grade_PCA.pkl")
#     columns = [f'equipment_{e}_grade' for e in equipments]
#     df_pca = pca.transform(df_scale[columns])
#     df.drop(columns, axis=1, inplace=True)
#     df_pca = pd.DataFrame(df_pca, columns=['equipment_grade_PCA1'])
#     df = pd.concat([df, df_pca], axis=1)

#     # euqipment setLevel
#     pca = joblib.load("C:\\Users\\user\\Code_Files_Jupyter\\Lostark\\Lostark-API-DA\\PCA\\equipment_setLevel_PCA.pkl")
#     columns = [f'equipment_{e}_setLevel' for e in equipments]
#     df_pca = pca.transform(df_scale[columns])
#     dfc.drop(columns, axis=1, inplace=True)
#     df_pca = pd.DataFrame(df_pca, columns=['equipment_setLevel_PCA1', 'equipment_setLevel_PCA2'])
#     dfc = pd.concat([dfc, df_pca], axis=1)

#     # euqipment quality
#     pca = joblib.load("C:\\Users\\user\\Code_Files_Jupyter\\Lostark\\Lostark-API-DA\\PCA\\equipment_quality_PCA.pkl")
#     columns = [f'equipment_{e}_quality' for e in equipments]
#     df_pca = pca.transform(df_scale[columns])
#     dfc.drop(columns, axis=1, inplace=True)
#     df_pca = pd.DataFrame(df_pca, columns=['equipment_quality_PCA1', 'equipment_quality_PCA2'])
#     dfc = pd.concat([dfc, df_pca], axis=1)
#     display(dfc)
    return df


## regex pattern
float_pattern = re.compile(r'\d+\.\d+')
int_pattern = re.compile(r'\d+')
# armory skill
resource_pattern = re.compile(r'마나|배터리|버블|충격|기공|기력|내공|영혼석')
# armory equipment
archemy_pattern = re.compile(r'\](.*?)Lv\.(\d+)')
plus_pattern = re.compile(r'([^\s]+)\s*\+([\d]+)')
bracelet_pattern = re.compile(r'\[.*?\[')
















