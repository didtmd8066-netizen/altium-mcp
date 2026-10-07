// 회로도 부품의 풋프린트 모델을 계획대로 바꾸고(APPLY), 다시 읽어 낸다(READ).
// {PLAN}, {OUT} 을 경로로 바꿔 run_altium_script 에 넣는다 (// 줄은 빼고).
//
// {PLAN}: `#<SchDoc 전체 경로>` 한 줄 뒤에 그 시트의 `지정자=풋프린트 이름` 줄들 (ANSI, CRLF).
//         바꿀 부품만 적는다 - 이미 같은 부품과 그대로 둘 부품은 계획에서 뺀다.
// - 기존 PCBLIB 모델을 전부 지우고 새 이름 하나를 Current 로 넣는다. 기존 모델에 IsCurrent := False 를
//   주는 방식은 모델이 하나뿐인 부품에서 반영되지 않는다.
// - 모델은 순회 중에 지우지 않는다: 하나 찾고 iterator 를 닫은 뒤 지우기를 되풀이한다.
// - 한 시트 안에서 같은 지정자를 가진 부품(멀티파트)은 전부 바꾼다.
// - 시트마다 PreProcess / PostProcess 로 묶어 Undo 가 시트당 1회다. 저장은 하지 않는다.
// READ 는 반드시 별도 호출로 돌린다. 결과는 계획 뒤에 `@경로` 와 `지정자=이름*;이름;` 줄 (* 가 Current).
//## APPLY
List1.LoadFromFile('{PLAN}');
I1 := 0;
B1 := 0;
while I1 < List1.Count do
begin
  S1 := List1[I1];
  I2 := I1 + 1;
  while (I2 < List1.Count) and (Copy(List1[I2], 1, 1) <> '#') do I2 := I2 + 1;
  Obj1 := nil;
  if Copy(S1, 1, 1) = '#' then Obj1 := SchServer.GetSchDocumentByPath(Copy(S1, 2, 999));
  if Obj1 = nil then SandboxLog('notopen: ' + ExtractFileName(Copy(S1, 2, 999)))
  else
  begin
    SandboxLog('doc ' + ExtractFileName(Copy(S1, 2, 999)));
    SchServer.ProcessControl.PreProcess(Obj1, '');
    Obj2 := Obj1.SchIterator_Create;
    Obj2.AddFilter_ObjectSet(MkSet(eSchComponent));
    Obj3 := Obj2.FirstSchObject;
    while Obj3 <> nil do
    begin
      S2 := Obj3.Designator.Text + '=';
      S3 := '';
      I3 := I1 + 1;
      while I3 < I2 do
      begin
        if Copy(List1[I3], 1, Length(S2)) = S2 then
        begin
          S3 := Copy(List1[I3], Length(S2) + 1, 999);
          I3 := I2;
        end;
        I3 := I3 + 1;
      end;
      if S3 <> '' then
      begin
        SchServer.RobotManager.SendMessage(Obj3.I_ObjectAddress, c_BroadCast, SCHM_BeginModify, c_NoEventData);
        S4 := 'x';
        while S4 = 'x' do
        begin
          Obj6 := nil;
          Obj4 := Obj3.SchIterator_Create;
          Obj4.AddFilter_ObjectSet(MkSet(eImplementation));
          Obj5 := Obj4.FirstSchObject;
          while Obj5 <> nil do
          begin
            if Obj5.ModelType = 'PCBLIB' then Obj6 := Obj5;
            Obj5 := Obj4.NextSchObject;
          end;
          Obj3.SchIterator_Destroy(Obj4);
          if Obj6 = nil then S4 := '' else Obj3.RemoveSchImplementation(Obj6);
        end;
        Obj5 := Obj3.AddSchImplementation;
        Obj5.ClearAllDatafileLinks;
        Obj5.ModelName := S3;
        Obj5.ModelType := 'PCBLIB';
        Obj5.IsCurrent := True;
        Obj5.UseComponentLibrary := False;
        Obj5.AddDataFileLink(S3, '', 'PCBLIB');
        SchServer.RobotManager.SendMessage(Obj3.I_ObjectAddress, c_BroadCast, SCHM_EndModify, c_NoEventData);
        B1 := B1 + 1;
      end;
      Obj3 := Obj2.NextSchObject;
    end;
    Obj1.SchIterator_Destroy(Obj2);
    SchServer.ProcessControl.PostProcess(Obj1, '');
    Obj1.GraphicallyInvalidate;
  end;
  I1 := I2;
end;
ResultText := 'set ' + IntToStr(B1);
//## READ
List1.LoadFromFile('{PLAN}');
I1 := 0;
B1 := 0;
I3 := List1.Count;
while I1 < I3 do
begin
  S1 := List1[I1];
  if Copy(S1, 1, 1) = '#' then
  begin
    Obj1 := SchServer.GetSchDocumentByPath(Copy(S1, 2, 999));
    if Obj1 <> nil then
    begin
      List1.Add('@' + Copy(S1, 2, 999));
      Obj2 := Obj1.SchIterator_Create;
      Obj2.AddFilter_ObjectSet(MkSet(eSchComponent));
      Obj3 := Obj2.FirstSchObject;
      while Obj3 <> nil do
      begin
        S2 := Obj3.Designator.Text + '=';
        Obj4 := Obj3.SchIterator_Create;
        Obj4.AddFilter_ObjectSet(MkSet(eImplementation));
        Obj5 := Obj4.FirstSchObject;
        while Obj5 <> nil do
        begin
          if Obj5.ModelType = 'PCBLIB' then
          begin
            S2 := S2 + Obj5.ModelName;
            if Obj5.IsCurrent then S2 := S2 + '*';
            S2 := S2 + ';';
          end;
          Obj5 := Obj4.NextSchObject;
        end;
        Obj3.SchIterator_Destroy(Obj4);
        List1.Add(S2);
        B1 := B1 + 1;
        Obj3 := Obj2.NextSchObject;
      end;
      Obj1.SchIterator_Destroy(Obj2);
    end;
  end;
  I1 := I1 + 1;
end;
List1.SaveToFile('{OUT}');
ResultText := 'read ' + IntToStr(B1);
