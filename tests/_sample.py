"""Build a minimal but structurally valid synthetic ``.dxp`` for tests.

It is not a real Spotfire file, but it reproduces the XML shapes the analyzer
walks: a Document with a Pages collection, a Page with a Visuals collection
(one native BarChart, one non-native ScatterPlot3D), a user document property,
and an embedded IronPython script that touches a document property and loads a
.NET assembly.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

SCRIPT = """import clr
clr.AddReference("Something")
from Spotfire.Dxp.Application import Document
def main():
    for i in range(10):
        Document.Properties["region"] = i
main()"""

ANALYSIS_DOCUMENT = f"""<?xml version="1.0" encoding="utf-8"?>
<AnalysisDocument>
  <Object>
    <Type><TypeObject FullTypeName="Spotfire.Dxp.Application.Document"/></Type>
    <Fields>
      <Field Name="Title"><String Value="Sales Dashboard"/></Field>
      <Field Name="Pages">
        <Elements>
          <Object>
            <Type><TypeObject FullTypeName="Spotfire.Dxp.Application.Page"/></Type>
            <Fields>
              <Field Name="Title"><String Value="Overview"/></Field>
              <Field Name="Visuals">
                <Elements>
                  <Object>
                    <Type><TypeObject FullTypeName="Spotfire.Dxp.Application.Visuals.BarChart"/></Type>
                    <Fields><Field Name="Title"><String Value="Revenue by region"/></Field></Fields>
                  </Object>
                  <Object>
                    <Type><TypeObject FullTypeName="Spotfire.Dxp.Application.Visuals.ScatterPlot3D"/></Type>
                    <Fields><Field Name="Title"><String Value="3D view"/></Field></Fields>
                  </Object>
                </Elements>
              </Field>
            </Fields>
          </Object>
        </Elements>
      </Field>
      <Field Name="DocumentProperties">
        <Elements>
          <Object>
            <Type><TypeObject FullTypeName="Spotfire.Dxp.Framework.DocumentModel.DataProperty"/></Type>
            <Fields>
              <Field Name="Name"><String Value="region"/></Field>
              <Field Name="Value"><String Value="North"/></Field>
              <Field Name="Attributes"><String Value=""/></Field>
            </Fields>
          </Object>
        </Elements>
      </Field>
      <Field Name="Script"><String Id="script1">{SCRIPT}</String></Field>
    </Fields>
  </Object>
</AnalysisDocument>
"""


def make_sample_dxp(path) -> Path:
    path = Path(path)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("AnalysisDocument.xml", ANALYSIS_DOCUMENT)
    return path
